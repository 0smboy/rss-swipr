"""
RSS Fetcher module to fetch and parse RSS feeds.
Based on old/rss_fetcher.py - maintains compatibility with training notebook.
"""
import feedparser
import requests
import re
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path
from urllib.parse import urlparse


class RSSFetcher:
    """Fetches and parses RSS feeds, storing entries in database."""

    # Root directory (parent of src/)
    ROOT_DIR = Path(__file__).parent.parent

    def __init__(self, db_path: str = "rss_reader.db", timeout: int = 30):
        """Initialize RSS fetcher."""
        self.db_path = self.ROOT_DIR / db_path
        self.timeout = timeout
        self.user_agent = 'RSS-Swipr/1.0'

    def _get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def get_all_feeds(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """Get all feeds from the database."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if active_only:
            cursor.execute("""
                SELECT * FROM feeds WHERE active = TRUE
                ORDER BY name
            """)
        else:
            cursor.execute("SELECT * FROM feeds ORDER BY name")

        feeds = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return feeds

    def fetch_feed(self, feed_id: int, feed_url: str, feed_name: str) -> Dict[str, Any]:
        """
        Fetch and parse a single RSS feed.
        Returns statistics about the fetch operation.
        """
        stats = {
            'feed_id': feed_id,
            'feed_name': feed_name,
            'feed_url': feed_url,
            'success': False,
            'entries_fetched': 0,
            'entries_new': 0,
            'entries_duplicate': 0,
            'error': None
        }

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Fetch feed with custom headers
            headers = {
                'User-Agent': self.user_agent,
                'Accept': 'application/rss+xml, application/xml, application/atom+xml, text/xml'
            }

            response = requests.get(
                feed_url,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=True
            )
            response.raise_for_status()

            # Parse feed
            feed = feedparser.parse(response.content)

            # Check for parsing errors
            if feed.bozo and not feed.entries:
                error_msg = f"Parse error: {feed.bozo_exception}"
                stats['error'] = error_msg
                self._record_feed_error(cursor, feed_id, error_msg)
                conn.commit()
                return stats

            # Update feed metadata
            feed_metadata = self._extract_feed_metadata(feed, response)
            feed_metadata['last_fetched'] = datetime.utcnow().isoformat()
            self._update_feed_metadata(cursor, feed_id, feed_metadata)

            # Process entries
            fetched_at = datetime.utcnow().isoformat()
            stats['entries_fetched'] = len(feed.entries)

            for entry in feed.entries:
                entry_data = self._extract_entry_data(entry, feed_id, fetched_at)

                # Try to insert entry
                try:
                    cursor.execute("""
                        INSERT INTO entries (
                            feed_id, guid, title, link, description, content,
                            content_html, summary, author, contributors,
                            published_at, updated_at_source, fetched_at,
                            enclosure_url, enclosure_type, enclosure_length,
                            categories, tags, comments_url, source_title, source_url,
                            permalink, word_count, has_media
                        ) VALUES (
                            :feed_id, :guid, :title, :link, :description, :content,
                            :content_html, :summary, :author, :contributors,
                            :published_at, :updated_at_source, :fetched_at,
                            :enclosure_url, :enclosure_type, :enclosure_length,
                            :categories, :tags, :comments_url, :source_title, :source_url,
                            :permalink, :word_count, :has_media
                        )
                    """, entry_data)
                    stats['entries_new'] += 1
                except sqlite3.IntegrityError:
                    # Duplicate entry (feed_id, guid combination already exists)
                    stats['entries_duplicate'] += 1

            # Reset error count on success
            self._reset_feed_errors(cursor, feed_id)
            conn.commit()
            stats['success'] = True

        except requests.exceptions.Timeout:
            error_msg = f"Timeout after {self.timeout}s"
            stats['error'] = error_msg
            self._record_feed_error(cursor, feed_id, error_msg)
            conn.commit()

        except requests.exceptions.RequestException as e:
            error_msg = f"Request error: {str(e)}"
            stats['error'] = error_msg
            self._record_feed_error(cursor, feed_id, error_msg)
            conn.commit()

        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            stats['error'] = error_msg
            try:
                self._record_feed_error(cursor, feed_id, error_msg)
                conn.commit()
            except:
                pass

        finally:
            conn.close()

        return stats

    def fetch_all_feeds(self, active_only: bool = True) -> Dict[str, Any]:
        """Fetch all active feeds. Returns summary stats."""
        feeds = self.get_all_feeds(active_only=active_only)
        results = []

        for feed in feeds:
            stats = self.fetch_feed(feed['id'], feed['url'], feed['name'])
            results.append(stats)

        return {
            'total_feeds': len(results),
            'successful': sum(1 for r in results if r['success']),
            'failed': sum(1 for r in results if r['error']),
            'new_entries': sum(r['entries_new'] for r in results),
            'results': results
        }

    def _extract_feed_metadata(self, feed: feedparser.FeedParserDict,
                               response: requests.Response) -> Dict[str, Any]:
        """Extract metadata from feed."""
        metadata = {}

        # Feed information
        if hasattr(feed, 'feed'):
            metadata['feed_title'] = feed.feed.get('title', '')
            metadata['feed_description'] = feed.feed.get('description', '') or feed.feed.get('subtitle', '')
            metadata['feed_language'] = feed.feed.get('language', '')
            metadata['feed_link'] = feed.feed.get('link', '')

            # Feed image
            if 'image' in feed.feed:
                metadata['feed_image_url'] = feed.feed.image.get('href', '')
            elif 'logo' in feed.feed:
                metadata['feed_image_url'] = feed.feed.get('logo', '')

        # HTTP caching headers
        if 'etag' in response.headers:
            metadata['etag'] = response.headers['etag']
        if 'last-modified' in response.headers:
            metadata['last_modified'] = response.headers['last-modified']

        return metadata

    def _extract_entry_data(self, entry: feedparser.FeedParserDict,
                           feed_id: int, fetched_at: str) -> Dict[str, Any]:
        """Extract all available data from an entry."""

        # Generate GUID (use id, link, or title as fallback)
        guid = entry.get('id') or entry.get('link') or entry.get('title', 'no-guid')

        # Parse dates
        published_at = self._parse_date(entry.get('published_parsed') or entry.get('updated_parsed'))
        updated_at_source = self._parse_date(entry.get('updated_parsed'))

        # Extract content (try multiple fields)
        content = ''
        content_html = ''

        if 'content' in entry and entry.content:
            content = entry.content[0].get('value', '')
            content_html = content
        elif 'summary_detail' in entry:
            content = entry.summary_detail.get('value', '')
            content_html = content

        # Get description/summary
        description = entry.get('description', '') or entry.get('summary', '')
        summary = entry.get('summary', '')

        # Author information
        author = entry.get('author', '') or entry.get('dc:creator', '')
        if not author and 'authors' in entry and entry.authors:
            author = ', '.join([a.get('name', '') for a in entry.authors if 'name' in a])

        # Contributors
        contributors = ''
        if 'contributors' in entry and entry.contributors:
            contributors = ', '.join([c.get('name', '') for c in entry.contributors if 'name' in c])

        # Categories/Tags
        categories = ''
        tags = ''
        if 'tags' in entry and entry.tags:
            tag_list = [tag.get('term', '') or tag.get('label', '') for tag in entry.tags]
            categories = ', '.join(tag_list)
            tags = categories

        # Enclosures (media attachments)
        enclosure_url = None
        enclosure_type = None
        enclosure_length = None
        has_media = False

        if 'enclosures' in entry and entry.enclosures:
            enc = entry.enclosures[0]
            enclosure_url = enc.get('href', '') or enc.get('url', '')
            enclosure_type = enc.get('type', '')
            enclosure_length = enc.get('length')
            has_media = bool(enclosure_url)

        # Media content (alternative to enclosures)
        if not has_media and 'media_content' in entry and entry.media_content:
            media = entry.media_content[0]
            enclosure_url = media.get('url', '')
            enclosure_type = media.get('type', '')
            has_media = bool(enclosure_url)

        # Comments
        comments_url = entry.get('comments', '')

        # Source information
        source_title = ''
        source_url = ''
        if 'source' in entry:
            source_title = entry.source.get('title', '')
            source_url = entry.source.get('href', '') or entry.source.get('url', '')

        # Extract permalink (for linkblogs)
        permalink = self._extract_permalink(entry, content_html or description or content)

        # Calculate word count
        text_content = description or content or summary
        word_count = len(text_content.split()) if text_content else 0

        return {
            'feed_id': feed_id,
            'guid': guid,
            'title': entry.get('title', 'No title'),
            'link': entry.get('link', ''),
            'description': description,
            'content': content,
            'content_html': content_html,
            'summary': summary,
            'author': author,
            'contributors': contributors,
            'published_at': published_at,
            'updated_at_source': updated_at_source,
            'fetched_at': fetched_at,
            'enclosure_url': enclosure_url,
            'enclosure_type': enclosure_type,
            'enclosure_length': enclosure_length,
            'categories': categories,
            'tags': tags,
            'comments_url': comments_url,
            'source_title': source_title,
            'source_url': source_url,
            'permalink': permalink,
            'word_count': word_count,
            'has_media': has_media
        }

    def _parse_date(self, date_tuple) -> Optional[str]:
        """Parse date from feedparser time tuple to ISO format."""
        if not date_tuple:
            return None

        try:
            # feedparser returns time.struct_time
            dt = datetime(*date_tuple[:6])
            return dt.isoformat()
        except (TypeError, ValueError):
            return None

    def _extract_permalink(self, entry: feedparser.FeedParserDict, html_content: str) -> Optional[str]:
        """
        Extract permalink to blog post (for linkblogs).

        For linkblogs like Daring Fireball, the main 'link' field points to the external article,
        but there's usually a permalink to the blog's own post in the content.
        """
        permalink = None

        # Strategy 1: Check feedburner:origLink (some feeds provide this)
        if hasattr(entry, 'feedburner_origlink'):
            permalink = entry.feedburner_origlink

        # Strategy 2: If guid is a URL and different from link, it's likely the permalink
        if not permalink:
            guid = entry.get('id', '') or entry.get('guid', '')
            link = entry.get('link', '')
            if guid and guid.startswith('http') and guid != link:
                permalink = guid

        # Strategy 3: Parse HTML content for permalink indicators
        if not permalink and html_content:
            # Daring Fireball pattern: <a href="URL" title="Permanent link to 'TITLE'">★</a>
            df_pattern = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*(?:title=["\']Permanent link to|>(?:\s*★\s*|Permanent link)</a>)'
            match = re.search(df_pattern, html_content, re.IGNORECASE)
            if match:
                permalink = match.group(1)

            # Generic permalink patterns
            if not permalink:
                permalink_patterns = [
                    r'<a[^>]+href=["\']([^"\']*permalink[^"\']*)["\']',
                    r'<a[^>]+href=["\']([^"\']*\/linked\/[^"\']*)["\']',
                    r'<a[^>]+class=["\'][^"\']*permalink[^"\']*["\'][^>]+href=["\']([^"\']+)["\']',
                ]

                for pattern in permalink_patterns:
                    match = re.search(pattern, html_content, re.IGNORECASE)
                    if match:
                        candidate = match.group(1)
                        if candidate != entry.get('link', ''):
                            permalink = candidate
                            break

            # Strategy 4: Look for links to the feed's own domain
            if not permalink:
                link = entry.get('link', '')
                if link:
                    url_pattern = r'href=["\']([^"\']+)["\']'
                    all_urls = re.findall(url_pattern, html_content)

                    try:
                        link_domain = urlparse(link).netloc
                        for url in all_urls:
                            if url.startswith('http'):
                                url_domain = urlparse(url).netloc
                                if url_domain == link_domain and url != link:
                                    if any(marker in url.lower() for marker in ['/linked/', '/post/', '/permalink', '/archive/']):
                                        permalink = url
                                        break
                    except:
                        pass

        return permalink

    def _update_feed_metadata(self, cursor, feed_id: int, metadata: Dict[str, Any]):
        """Update feed metadata after successful fetch."""
        set_clauses = []
        values = []

        for key, value in metadata.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)

        set_clauses.append("updated_at = ?")
        values.append(datetime.utcnow().isoformat())
        values.append(feed_id)

        cursor.execute(f"""
            UPDATE feeds
            SET {', '.join(set_clauses)}
            WHERE id = ?
        """, values)

    def _record_feed_error(self, cursor, feed_id: int, error_message: str):
        """Record an error for a feed."""
        cursor.execute("""
            UPDATE feeds
            SET error_count = error_count + 1,
                last_error = ?,
                updated_at = ?
            WHERE id = ?
        """, (error_message, datetime.utcnow().isoformat(), feed_id))

    def _reset_feed_errors(self, cursor, feed_id: int):
        """Reset error count after successful fetch."""
        cursor.execute("""
            UPDATE feeds
            SET error_count = 0,
                last_error = NULL,
                updated_at = ?
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), feed_id))

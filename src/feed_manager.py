"""
Feed Manager for RSS Swipr app.
Handles CSV feed import, listing, and management.
"""
import csv
import io
import re
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Tuple
from urllib.parse import urlparse


class FeedManager:
    """Manages RSS feed imports and operations."""

    # Root directory (parent of src/)
    ROOT_DIR = Path(__file__).parent.parent

    def __init__(self, rss_db_path: str = "rss_reader.db"):
        """Initialize with RSS database path."""
        self.rss_db_path = self.ROOT_DIR / rss_db_path
        self._init_database()

    def _init_database(self):
        """Create database tables if they don't exist."""
        conn = sqlite3.connect(str(self.rss_db_path))
        cursor = conn.cursor()

        # Create feeds table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                last_fetched TIMESTAMP,
                fetch_interval INTEGER DEFAULT 3600,
                active BOOLEAN DEFAULT TRUE,
                error_count INTEGER DEFAULT 0,
                last_error TEXT,
                etag TEXT,
                last_modified TEXT,
                feed_title TEXT,
                feed_description TEXT,
                feed_language TEXT,
                feed_link TEXT,
                feed_image_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create entries table with comprehensive fields (matches old/database.py)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id INTEGER NOT NULL,
                guid TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT,
                description TEXT,
                content TEXT,
                content_html TEXT,
                summary TEXT,
                author TEXT,
                contributors TEXT,
                published_at TIMESTAMP,
                updated_at_source TIMESTAMP,
                fetched_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                -- Media and enclosures
                enclosure_url TEXT,
                enclosure_type TEXT,
                enclosure_length INTEGER,

                -- Additional metadata
                categories TEXT,
                tags TEXT,
                comments_url TEXT,
                source_title TEXT,
                source_url TEXT,
                permalink TEXT,

                -- Technical metadata
                word_count INTEGER,
                has_media BOOLEAN DEFAULT FALSE,

                FOREIGN KEY (feed_id) REFERENCES feeds(id) ON DELETE CASCADE,
                UNIQUE(feed_id, guid)
            )
        """)

        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feeds_active ON feeds(active)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_feed_published ON entries(feed_id, published_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_fetched ON entries(fetched_at DESC)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_entries_guid ON entries(guid)")

        conn.commit()
        conn.close()
        print(f"[INFO] Database initialized at {self.rss_db_path}")

    def _get_connection(self):
        """Get database connection."""
        conn = sqlite3.connect(str(self.rss_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def validate_url(self, url: str) -> Tuple[bool, str]:
        """Validate a feed URL.

        Returns:
            (is_valid, cleaned_url_or_error)
        """
        url = url.strip()

        if not url:
            return False, "Empty URL"

        # Add https if no scheme
        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'https://' + url

        try:
            parsed = urlparse(url)
            if not parsed.netloc:
                return False, "Invalid URL format"
            return True, url
        except Exception as e:
            return False, f"Invalid URL: {str(e)}"

    def parse_csv(self, csv_content: str) -> Tuple[List[Dict[str, str]], List[str]]:
        """Parse CSV content into feed list.

        Expected format: name,url (with or without header)

        Returns:
            (feeds_list, errors_list)
        """
        feeds = []
        errors = []

        # Handle different line endings
        csv_content = csv_content.replace('\r\n', '\n').replace('\r', '\n')

        try:
            # Try to detect if first row is header
            lines = csv_content.strip().split('\n')
            if not lines:
                return [], ["Empty CSV content"]

            first_line = lines[0].lower()
            has_header = 'name' in first_line and 'url' in first_line

            reader = csv.reader(io.StringIO(csv_content))

            for i, row in enumerate(reader):
                # Skip header
                if i == 0 and has_header:
                    continue

                if not row:
                    continue

                # Handle different column counts
                if len(row) < 2:
                    # Might be just URL
                    if len(row) == 1 and row[0].strip():
                        url = row[0].strip()
                        is_valid, result = self.validate_url(url)
                        if is_valid:
                            # Extract name from URL
                            parsed = urlparse(result)
                            name = parsed.netloc.replace('www.', '')
                            feeds.append({'name': name, 'url': result})
                        else:
                            errors.append(f"Row {i+1}: {result}")
                    continue

                name = row[0].strip()
                url = row[1].strip()

                if not name and not url:
                    continue

                is_valid, result = self.validate_url(url)
                if is_valid:
                    feeds.append({
                        'name': name or urlparse(result).netloc,
                        'url': result
                    })
                else:
                    errors.append(f"Row {i+1} ({name}): {result}")

        except csv.Error as e:
            errors.append(f"CSV parsing error: {str(e)}")

        return feeds, errors

    def import_feeds(self, feeds: List[Dict[str, str]]) -> Dict[str, Any]:
        """Import parsed feeds into database.

        Returns:
            {added: int, skipped: int, errors: list}
        """
        added = 0
        skipped = 0
        errors = []

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            for feed in feeds:
                try:
                    cursor.execute("""
                        INSERT INTO feeds (name, url, active)
                        VALUES (?, ?, TRUE)
                    """, (feed['name'], feed['url']))
                    added += 1
                except sqlite3.IntegrityError:
                    # URL already exists
                    skipped += 1
                except Exception as e:
                    errors.append(f"{feed['name']}: {str(e)}")

            conn.commit()
        except Exception as e:
            conn.rollback()
            errors.append(f"Database error: {str(e)}")
        finally:
            conn.close()

        return {
            'added': added,
            'skipped': skipped,
            'errors': errors
        }

    def import_csv(self, csv_content: str) -> Dict[str, Any]:
        """Parse and import feeds from CSV content.

        Returns full result with parse and import stats.
        """
        feeds, parse_errors = self.parse_csv(csv_content)

        if not feeds:
            return {
                'success': False,
                'feeds_parsed': 0,
                'feeds_added': 0,
                'feeds_skipped': 0,
                'errors': parse_errors or ["No valid feeds found in CSV"]
            }

        import_result = self.import_feeds(feeds)

        return {
            'success': True,
            'feeds_parsed': len(feeds),
            'feeds_added': import_result['added'],
            'feeds_skipped': import_result['skipped'],
            'errors': parse_errors + import_result['errors']
        }

    def get_feeds(self) -> List[Dict[str, Any]]:
        """Get all feeds with entry counts."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT
                    f.id,
                    f.name,
                    f.url,
                    f.active,
                    f.last_fetched,
                    f.error_count,
                    f.last_error,
                    COUNT(e.id) as entry_count
                FROM feeds f
                LEFT JOIN entries e ON f.id = e.feed_id
                GROUP BY f.id
                ORDER BY f.name
            """)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def delete_feed(self, feed_id: int) -> Tuple[bool, str]:
        """Delete a feed and all its entries.

        Returns:
            (success, message)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Check if feed exists
            cursor.execute("SELECT name FROM feeds WHERE id = ?", (feed_id,))
            row = cursor.fetchone()
            if not row:
                return False, "Feed not found"

            feed_name = row['name']

            # Delete entries first (foreign key)
            cursor.execute("DELETE FROM entries WHERE feed_id = ?", (feed_id,))
            entries_deleted = cursor.rowcount

            # Delete feed
            cursor.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))

            conn.commit()
            return True, f"Deleted '{feed_name}' and {entries_deleted} entries"

        except Exception as e:
            conn.rollback()
            return False, f"Error deleting feed: {str(e)}"
        finally:
            conn.close()

    def toggle_feed(self, feed_id: int) -> Tuple[bool, bool]:
        """Toggle feed active status.

        Returns:
            (success, new_active_status)
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE feeds SET active = NOT active WHERE id = ?
            """, (feed_id,))

            cursor.execute("SELECT active FROM feeds WHERE id = ?", (feed_id,))
            row = cursor.fetchone()

            conn.commit()
            return True, row['active'] if row else False

        except Exception as e:
            conn.rollback()
            return False, False
        finally:
            conn.close()

    def get_feed_stats(self) -> Dict[str, Any]:
        """Get overall feed statistics."""
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT COUNT(*) FROM feeds")
            total_feeds = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM feeds WHERE active = TRUE")
            active_feeds = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM entries")
            total_entries = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM feeds WHERE error_count > 0
            """)
            feeds_with_errors = cursor.fetchone()[0]

            return {
                'total_feeds': total_feeds,
                'active_feeds': active_feeds,
                'inactive_feeds': total_feeds - active_feeds,
                'total_entries': total_entries,
                'feeds_with_errors': feeds_with_errors
            }
        finally:
            conn.close()

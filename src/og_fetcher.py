"""
Open Graph Fetcher for RSS Swipr app.
Fetches and caches OG metadata (title, description, image) for articles.
"""
import asyncio
import re
from html import unescape
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin
import aiohttp
from aiohttp import ClientTimeout


class OGFetcher:
    """Fetches Open Graph metadata from URLs."""

    # Common OG tags to extract
    OG_TAGS = ['og:title', 'og:description', 'og:image', 'og:site_name']

    # Fallback meta tags
    FALLBACK_TAGS = {
        'og:title': ['twitter:title', 'title'],
        'og:description': ['twitter:description', 'description'],
        'og:image': ['twitter:image', 'twitter:image:src'],
    }

    def __init__(self, db, timeout: int = 10, max_concurrent: int = 5):
        """Initialize with tracking database reference.

        Args:
            db: TrackingDatabase instance for caching
            timeout: Request timeout in seconds
            max_concurrent: Max concurrent requests
        """
        self.db = db
        self.timeout = ClientTimeout(total=timeout)
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; RSSReader/1.0)',
            'Accept': 'text/html,application/xhtml+xml',
        }

    def _extract_meta_content(self, html: str, property_name: str) -> Optional[str]:
        """Extract content from meta tag by property or name."""
        # Try property attribute (OG style)
        pattern = rf'<meta[^>]+property=["\']?{re.escape(property_name)}["\']?[^>]+content=["\']([^"\']+)["\']'
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return unescape(match.group(1).strip())

        # Try reversed order (content before property)
        pattern = rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']?{re.escape(property_name)}["\']?'
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return unescape(match.group(1).strip())

        # Try name attribute (Twitter/standard style)
        pattern = rf'<meta[^>]+name=["\']?{re.escape(property_name)}["\']?[^>]+content=["\']([^"\']+)["\']'
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return unescape(match.group(1).strip())

        # Try reversed order for name
        pattern = rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']?{re.escape(property_name)}["\']?'
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return unescape(match.group(1).strip())

        return None

    def _extract_title(self, html: str) -> Optional[str]:
        """Extract title from <title> tag."""
        match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        if match:
            return unescape(match.group(1).strip())
        return None

    def _parse_og_data(self, html: str, base_url: str) -> Dict[str, Optional[str]]:
        """Parse OG metadata from HTML.

        Args:
            html: Raw HTML content
            base_url: Base URL for resolving relative image URLs

        Returns:
            Dict with og_title, og_description, og_image, og_site_name
        """
        result = {
            'og_title': None,
            'og_description': None,
            'og_image': None,
            'og_site_name': None,
        }

        # Extract primary OG tags
        for tag in self.OG_TAGS:
            key = tag.replace(':', '_')
            value = self._extract_meta_content(html, tag)

            if not value and tag in self.FALLBACK_TAGS:
                # Try fallback tags
                for fallback in self.FALLBACK_TAGS[tag]:
                    if fallback == 'title':
                        value = self._extract_title(html)
                    else:
                        value = self._extract_meta_content(html, fallback)
                    if value:
                        break

            result[key] = value

        # Resolve relative image URLs
        if result['og_image'] and not result['og_image'].startswith(('http://', 'https://')):
            result['og_image'] = urljoin(base_url, result['og_image'])

        return result

    def _normalize_payload(self, raw: Dict[str, Any], entry_id: int) -> Dict[str, Any]:
        """Normalize OG metadata into a consistent response payload."""
        title = raw.get('title')
        if title is None:
            title = raw.get('og_title')

        description = raw.get('description')
        if description is None:
            description = raw.get('og_description')

        image = raw.get('image')
        if image is None:
            image = raw.get('og_image')

        site_name = raw.get('site_name')
        if site_name is None:
            site_name = raw.get('og_site_name')

        error = raw.get('error')
        if error is None:
            error = raw.get('fetch_error')

        payload = {
            'entry_id': entry_id,
            'title': title,
            'description': description,
            'image': image,
            'site_name': site_name,
            'error': error,
            # Legacy aliases for compatibility.
            'og_title': title,
            'og_description': description,
            'og_image': image,
            'og_site_name': site_name,
            'fetch_error': error
        }

        if raw.get('fetched_at'):
            payload['fetched_at'] = raw.get('fetched_at')

        return payload

    def _storage_payload(self, normalized: Dict[str, Any]) -> Dict[str, Any]:
        """Create DB payload from normalized metadata."""
        return {
            'title': normalized.get('title'),
            'description': normalized.get('description'),
            'image': normalized.get('image'),
            'site_name': normalized.get('site_name'),
            'error': normalized.get('error')
        }

    async def _fetch_url(self, session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
        """Fetch and parse a single URL.

        Returns:
            Dict with OG data or error
        """
        async with self.semaphore:
            try:
                async with session.get(url, headers=self.headers, allow_redirects=True) as response:
                    if response.status != 200:
                        return {'error': f'HTTP {response.status}'}

                    # Read limited content (first 100KB should have meta tags)
                    content = await response.content.read(102400)

                    # Try to decode
                    try:
                        html = content.decode('utf-8')
                    except UnicodeDecodeError:
                        html = content.decode('latin-1', errors='ignore')

                    # Parse OG data
                    og_data = self._parse_og_data(html, str(response.url))
                    og_data['error'] = None
                    return og_data

            except asyncio.TimeoutError:
                return {'error': 'Timeout'}
            except aiohttp.ClientError as e:
                return {'error': f'Request failed: {str(e)[:100]}'}
            except Exception as e:
                return {'error': f'Error: {str(e)[:100]}'}

    async def fetch_og(self, entry_id: int, url: str, force: bool = False) -> Dict[str, Any]:
        """Fetch OG data for a single entry.

        Args:
            entry_id: Entry ID for caching
            url: URL to fetch
            force: If True, bypass cache

        Returns:
            Dict with OG data
        """
        # Check cache first
        if not force:
            cached = self.db.get_og_metadata(entry_id)
            if cached:
                return self._normalize_payload(dict(cached), entry_id)

        # Fetch from URL
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            fetched = await self._fetch_url(session, url)

        normalized = self._normalize_payload(fetched, entry_id)

        # Cache result
        self.db.save_og_metadata(entry_id=entry_id, og_data=self._storage_payload(normalized))

        return normalized

    async def fetch_batch(self, entries: List[Dict[str, Any]], force: bool = False) -> List[Dict[str, Any]]:
        """Fetch OG data for multiple entries.

        Args:
            entries: List of dicts with 'id' and 'link' keys
            force: If True, bypass cache

        Returns:
            List of OG data dicts
        """
        results = []

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = []

            for entry in entries:
                entry_id = entry.get('id')
                url = entry.get('link')

                if not entry_id or not url:
                    continue

                # Check cache first
                if not force:
                    cached = self.db.get_og_metadata(entry_id)
                    if cached:
                        results.append(self._normalize_payload(dict(cached), entry_id))
                        continue

                # Add to fetch tasks
                tasks.append(self._fetch_with_entry_id(session, entry_id, url))

            # Fetch uncached entries
            if tasks:
                fetched = await asyncio.gather(*tasks, return_exceptions=True)
                for item in fetched:
                    if isinstance(item, Exception):
                        continue
                    results.append(item)

        return results

    async def _fetch_with_entry_id(self, session: aiohttp.ClientSession, entry_id: int, url: str) -> Dict[str, Any]:
        """Fetch and cache OG data for an entry."""
        fetched = await self._fetch_url(session, url)
        normalized = self._normalize_payload(fetched, entry_id)

        # Cache result
        self.db.save_og_metadata(entry_id=entry_id, og_data=self._storage_payload(normalized))

        return normalized


def fetch_og_sync(db, entry_id: int, url: str, force: bool = False) -> Dict[str, Any]:
    """Synchronous wrapper for fetching OG data.

    Use this from Flask routes.
    """
    fetcher = OGFetcher(db)

    # Run async code in sync context
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(fetcher.fetch_og(entry_id, url, force))

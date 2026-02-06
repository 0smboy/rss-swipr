"""
Tracking database for RSS Swipr app.
Stores user votes, link opens, and time spent on posts.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

# Root directory (parent of src/)
ROOT_DIR = Path(__file__).parent.parent


class TrackingDatabase:
    """Database for tracking user engagement with RSS posts."""

    def __init__(self, rss_db_path: str = "rss_reader.db",
                 tracking_db_path: str = "tracking.db"):
        """Initialize tracking database."""
        self.rss_db_path = str(ROOT_DIR / rss_db_path)
        self.tracking_db_path = str(ROOT_DIR / tracking_db_path)
        self.init_database()
    
    @contextmanager
    def get_connection(self, db_path: Optional[str] = None):
        """Context manager for database connections."""
        path = db_path or self.tracking_db_path
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def init_database(self):
        """Create tracking tables."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # User votes (like/neutral/dislike)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    vote TEXT NOT NULL CHECK(vote IN ('like', 'neutral', 'dislike')),
                    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(entry_id)
                )
            """)
            
            # Link opens tracking
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS link_opens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Time spent on each post
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS time_spent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    seconds INTEGER NOT NULL,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Session tracking for gamification
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    posts_reviewed INTEGER DEFAULT 0
                )
            """)
            
            # Open Graph metadata cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS og_metadata (
                    entry_id INTEGER PRIMARY KEY,
                    og_title TEXT,
                    og_description TEXT,
                    og_image TEXT,
                    og_site_name TEXT,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    fetch_error TEXT
                )
            """)

            # Model registry for uploaded models
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    filename TEXT NOT NULL UNIQUE,
                    is_active BOOLEAN DEFAULT FALSE,
                    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_votes_entry
                ON user_votes(entry_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_opens_entry
                ON link_opens(entry_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_time_entry
                ON time_spent(entry_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_models_active
                ON models(is_active)
            """)
    
    def get_random_unvoted_post(self, exclude_ids: List[int] = None) -> Optional[Dict[str, Any]]:
        """Get a random post that hasn't been voted on yet. Prioritizes recent posts with feed diversity.

        Args:
            exclude_ids: List of entry IDs to exclude (e.g., posts already in queue)
        """
        exclude_ids = exclude_ids or []

        # Connect to RSS database
        with self.get_connection(self.rss_db_path) as rss_conn:
            cursor = rss_conn.cursor()

            # Get entry IDs that have been voted on
            with self.get_connection() as tracking_conn:
                tracking_cursor = tracking_conn.cursor()
                tracking_cursor.execute("SELECT entry_id FROM user_votes")
                voted_ids = [row[0] for row in tracking_cursor.fetchall()]

            # Combine voted + exclude IDs
            all_exclude = list(set(voted_ids + exclude_ids))

            # Get recent unvoted entry with randomization for feed diversity
            # Strategy: Sort by published date, then pick randomly from top 20% to ensure variety
            if all_exclude:
                placeholders = ','.join('?' * len(all_exclude))
                query = f"""
                    SELECT e.*, f.name as feed_name
                    FROM entries e
                    JOIN feeds f ON e.feed_id = f.id
                    WHERE e.id NOT IN ({placeholders})
                    ORDER BY e.published_at DESC, RANDOM()
                    LIMIT 1
                """
                cursor.execute(query, all_exclude)
            else:
                cursor.execute("""
                    SELECT e.*, f.name as feed_name
                    FROM entries e
                    JOIN feeds f ON e.feed_id = f.id
                    ORDER BY RANDOM()
                    LIMIT 1
                """)

            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_all_unvoted_posts(self, limit: int = 50, exclude_ids: List[int] = None) -> List[Dict[str, Any]]:
        """Get multiple unvoted posts for ML scoring with feed diversity.

        Uses a round-robin approach to ensure posts from different feeds are included,
        preventing any single high-volume feed (like arXiv) from dominating.

        Args:
            limit: Maximum number of posts to return
            exclude_ids: List of entry IDs to exclude (e.g., posts already in queue)
        """
        exclude_ids = exclude_ids or []

        with self.get_connection(self.rss_db_path) as rss_conn:
            cursor = rss_conn.cursor()

            # Get voted IDs
            with self.get_connection() as tracking_conn:
                tracking_cursor = tracking_conn.cursor()
                tracking_cursor.execute("SELECT entry_id FROM user_votes")
                voted_ids = [row[0] for row in tracking_cursor.fetchall()]

            # Combine voted + exclude IDs
            all_exclude = list(set(voted_ids + exclude_ids))

            # Get recent unvoted entries with feed diversity
            # Uses ROW_NUMBER to rank posts within each feed, then orders by rank
            # This ensures we get the newest post from each feed first, then second-newest, etc.
            if all_exclude:
                placeholders = ','.join('?' * len(all_exclude))
                query = f"""
                    WITH ranked AS (
                        SELECT e.*, f.name as feed_name,
                               ROW_NUMBER() OVER (PARTITION BY e.feed_id ORDER BY e.published_at DESC) as feed_rank
                        FROM entries e
                        JOIN feeds f ON e.feed_id = f.id
                        WHERE e.id NOT IN ({placeholders})
                    )
                    SELECT * FROM ranked
                    ORDER BY feed_rank, published_at DESC
                    LIMIT ?
                """
                cursor.execute(query, all_exclude + [limit])
            else:
                cursor.execute("""
                    WITH ranked AS (
                        SELECT e.*, f.name as feed_name,
                               ROW_NUMBER() OVER (PARTITION BY e.feed_id ORDER BY e.published_at DESC) as feed_rank
                        FROM entries e
                        JOIN feeds f ON e.feed_id = f.id
                    )
                    SELECT * FROM ranked
                    ORDER BY feed_rank, published_at DESC
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_random_unvoted_posts(self, limit: int = 3, exclude_ids: List[int] = None) -> List[Dict[str, Any]]:
        """Get multiple random unvoted posts for fallback. Used when ML scoring fails."""
        exclude_ids = exclude_ids or []
        
        with self.get_connection(self.rss_db_path) as rss_conn:
            cursor = rss_conn.cursor()
            
            # Get voted IDs
            with self.get_connection() as tracking_conn:
                tracking_cursor = tracking_conn.cursor()
                tracking_cursor.execute("SELECT entry_id FROM user_votes")
                voted_ids = [row[0] for row in tracking_cursor.fetchall()]
            
            # Combine voted + exclude IDs
            all_exclude = list(set(voted_ids + exclude_ids))
            
            if all_exclude:
                placeholders = ','.join('?' * len(all_exclude))
                query = f"""
                    SELECT e.*, f.name as feed_name
                    FROM entries e
                    JOIN feeds f ON e.feed_id = f.id
                    WHERE e.id NOT IN ({placeholders})
                    ORDER BY RANDOM()
                    LIMIT ?
                """
                cursor.execute(query, all_exclude + [limit])
            else:
                cursor.execute("""
                    SELECT e.*, f.name as feed_name
                    FROM entries e
                    JOIN feeds f ON e.feed_id = f.id
                    ORDER BY RANDOM()
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def record_vote(self, entry_id: int, vote: str) -> bool:
        """Record a user vote (like/neutral/dislike)."""
        if vote not in ['like', 'neutral', 'dislike']:
            return False
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO user_votes (entry_id, vote)
                    VALUES (?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET
                        vote = excluded.vote,
                        voted_at = CURRENT_TIMESTAMP
                """, (entry_id, vote))
                return True
            except Exception:
                return False
    
    def record_link_open(self, entry_id: int):
        """Record when a user opens an article link."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO link_opens (entry_id)
                VALUES (?)
            """, (entry_id,))
    
    def record_time_spent(self, entry_id: int, seconds: int):
        """Record time spent viewing a post."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO time_spent (entry_id, seconds)
                VALUES (?, ?)
            """, (entry_id, seconds))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics for gamification."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Vote counts
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN vote = 'like' THEN 1 ELSE 0 END) as likes,
                    SUM(CASE WHEN vote = 'neutral' THEN 1 ELSE 0 END) as neutral,
                    SUM(CASE WHEN vote = 'dislike' THEN 1 ELSE 0 END) as dislikes
                FROM user_votes
            """)
            vote_stats = dict(cursor.fetchone())
            
            # Link opens
            cursor.execute("SELECT COUNT(*) as opens FROM link_opens")
            opens = cursor.fetchone()[0]
            
            # Total time spent
            cursor.execute("SELECT COALESCE(SUM(seconds), 0) as total_seconds FROM time_spent")
            total_seconds = cursor.fetchone()[0]
            
            # Today's activity
            cursor.execute("""
                SELECT COUNT(*) as today_votes
                FROM user_votes
                WHERE DATE(voted_at) = DATE('now')
            """)
            today_votes = cursor.fetchone()[0]
            
            # Get total posts in RSS database
            with self.get_connection(self.rss_db_path) as rss_conn:
                rss_cursor = rss_conn.cursor()
                rss_cursor.execute("SELECT COUNT(*) FROM entries")
                total_posts = rss_cursor.fetchone()[0]
            
            return {
                'total_posts': total_posts,
                'posts_reviewed': vote_stats['total'],
                'posts_remaining': total_posts - vote_stats['total'],
                'likes': vote_stats['likes'],
                'neutral': vote_stats['neutral'],
                'dislikes': vote_stats['dislikes'],
                'links_opened': opens,
                'total_time_seconds': total_seconds,
                'total_time_minutes': round(total_seconds / 60, 1),
                'today_votes': today_votes,
                'completion_percent': round((vote_stats['total'] / total_posts * 100) if total_posts > 0 else 0, 1)
            }
    
    def get_entry_details(self, entry_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed tracking data for a specific entry."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get vote
            cursor.execute("SELECT vote, voted_at FROM user_votes WHERE entry_id = ?", (entry_id,))
            vote_row = cursor.fetchone()
            
            # Get open count
            cursor.execute("SELECT COUNT(*) FROM link_opens WHERE entry_id = ?", (entry_id,))
            open_count = cursor.fetchone()[0]
            
            # Get total time
            cursor.execute("SELECT COALESCE(SUM(seconds), 0) FROM time_spent WHERE entry_id = ?", (entry_id,))
            total_time = cursor.fetchone()[0]
            
            return {
                'entry_id': entry_id,
                'vote': dict(vote_row)['vote'] if vote_row else None,
                'voted_at': dict(vote_row)['voted_at'] if vote_row else None,
                'open_count': open_count,
                'total_time_seconds': total_time
            }

    # =====================
    # Open Graph Methods
    # =====================

    def save_og_metadata(self, entry_id: int, og_data: Optional[Dict[str, Any]] = None, **kwargs) -> bool:
        """Save Open Graph metadata for an entry.

        Accepts both normalized keys (`title`, `description`, `image`, `site_name`, `error`)
        and legacy keys (`og_title`, `og_description`, `og_image`, `og_site_name`, `fetch_error`).
        """
        payload: Dict[str, Any] = {}
        if isinstance(og_data, dict):
            payload.update(og_data)
        if kwargs:
            payload.update(kwargs)

        title = payload.get('title')
        if title is None:
            title = payload.get('og_title')

        description = payload.get('description')
        if description is None:
            description = payload.get('og_description')

        image = payload.get('image')
        if image is None:
            image = payload.get('og_image')

        site_name = payload.get('site_name')
        if site_name is None:
            site_name = payload.get('og_site_name')

        error = payload.get('error')
        if error is None:
            error = payload.get('fetch_error')

        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO og_metadata (entry_id, og_title, og_description, og_image, og_site_name, fetch_error)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(entry_id) DO UPDATE SET
                        og_title = excluded.og_title,
                        og_description = excluded.og_description,
                        og_image = excluded.og_image,
                        og_site_name = excluded.og_site_name,
                        fetch_error = excluded.fetch_error,
                        fetched_at = CURRENT_TIMESTAMP
                """, (
                    entry_id,
                    title,
                    description,
                    image,
                    site_name,
                    error
                ))
                return True
            except Exception:
                return False

    def get_og_metadata(self, entry_id: int) -> Optional[Dict[str, Any]]:
        """Get cached Open Graph metadata for an entry."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT og_title, og_description, og_image, og_site_name, fetched_at, fetch_error
                FROM og_metadata WHERE entry_id = ?
            """, (entry_id,))
            row = cursor.fetchone()
            if row:
                title = row['og_title']
                description = row['og_description']
                image = row['og_image']
                site_name = row['og_site_name']
                error = row['fetch_error']
                return {
                    'entry_id': entry_id,
                    'title': title,
                    'description': description,
                    'image': image,
                    'site_name': site_name,
                    'fetched_at': row['fetched_at'],
                    'error': error,
                    # Legacy aliases for compatibility.
                    'og_title': title,
                    'og_description': description,
                    'og_image': image,
                    'og_site_name': site_name,
                    'fetch_error': error
                }
            return None

    # =====================
    # Model Registry Methods
    # =====================

    def save_model(self, name: str, filename: str, metadata: str = None) -> int:
        """Save a model to the registry. Returns model ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO models (name, filename, metadata)
                VALUES (?, ?, ?)
            """, (name, filename, metadata))
            return cursor.lastrowid

    def get_models(self) -> List[Dict[str, Any]]:
        """Get all registered models."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, filename, is_active, uploaded_at, metadata
                FROM models ORDER BY uploaded_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_active_model(self) -> Optional[Dict[str, Any]]:
        """Get the currently active model."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, filename, is_active, uploaded_at, metadata
                FROM models WHERE is_active = TRUE
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def activate_model(self, model_id: int) -> bool:
        """Set a model as active, deactivate all others."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("UPDATE models SET is_active = FALSE")
                cursor.execute("UPDATE models SET is_active = TRUE WHERE id = ?", (model_id,))
                return cursor.rowcount > 0
            except Exception:
                return False

    def delete_model(self, model_id: int) -> bool:
        """Delete a model from the registry."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("DELETE FROM models WHERE id = ?", (model_id,))
                return cursor.rowcount > 0
            except Exception:
                return False

    def get_model_by_id(self, model_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific model by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, filename, is_active, uploaded_at, metadata
                FROM models WHERE id = ?
            """, (model_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # =====================
    # Training Data Import
    # =====================

    def import_training_data(self, df) -> Dict[str, Any]:
        """Import training data from a DataFrame (CSV format).

        Matches entries by link URL to find entry_id in current database.
        Imports votes, link opens, and time spent.

        Returns:
            Dict with import statistics
        """
        import sqlite3

        # Build link -> entry_id mapping from rss_reader.db
        rss_conn = sqlite3.connect(self.rss_db_path)
        rss_conn.row_factory = sqlite3.Row
        cursor = rss_conn.cursor()
        cursor.execute("SELECT id, link FROM entries WHERE link IS NOT NULL")
        link_to_id = {row['link']: row['id'] for row in cursor.fetchall()}
        rss_conn.close()

        stats = {
            'total_rows': len(df),
            'votes_imported': 0,
            'votes_skipped': 0,
            'opens_imported': 0,
            'time_imported': 0,
            'entries_not_found': 0
        }

        with self.get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df.iterrows():
                link = row.get('link')
                if not link or link not in link_to_id:
                    stats['entries_not_found'] += 1
                    continue

                entry_id = link_to_id[link]

                # Import vote
                vote = row.get('vote')
                if vote and vote in ('like', 'neutral', 'dislike'):
                    try:
                        voted_at = row.get('voted_at')
                        cursor.execute("""
                            INSERT OR REPLACE INTO user_votes (entry_id, vote, voted_at)
                            VALUES (?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                        """, (entry_id, vote, voted_at))
                        stats['votes_imported'] += 1
                    except Exception:
                        stats['votes_skipped'] += 1

                # Import link opens (create N records for open_count)
                open_count = int(row.get('open_count', 0) or 0)
                if open_count > 0:
                    for _ in range(open_count):
                        cursor.execute("""
                            INSERT INTO link_opens (entry_id) VALUES (?)
                        """, (entry_id,))
                    stats['opens_imported'] += open_count

                # Import time spent
                total_time = int(row.get('total_time', 0) or 0)
                if total_time > 0:
                    cursor.execute("""
                        INSERT INTO time_spent (entry_id, seconds) VALUES (?, ?)
                    """, (entry_id, total_time))
                    stats['time_imported'] += 1

        return stats

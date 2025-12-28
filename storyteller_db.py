import sqlite3
import logging
import os
import json
import time
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

class StorytellerDB:
    def __init__(self, db_path=None, **kwargs):
        if db_path is None:
            db_path = os.getenv("STORYTELLER_DB_PATH", "/data/storyteller.db")
        self.db_path = Path(db_path)
        logger.info(f"Initialized StorytellerDB at {self.db_path}")

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def check_connection(self):
        """REQUIRED BY main.py: Validates the DB is accessible."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM position")
                count = cursor.fetchone()[0]
                logger.info(f"✅ Storyteller DB connected ({count} positions tracked)")
                return True
        except Exception as e:
            logger.error(f"❌ Storyteller DB connection FAILED: {e}")
            return False

    def _parse_timestamp(self, ts_val):
        """Converts DB timestamp to Milliseconds (Number)"""
        if not ts_val: return 0
        try:
            val = float(ts_val)
            if val < 10000000000: # Convert Seconds -> MS
                return int(val * 1000)
            return int(val)
        except (ValueError, TypeError):
            try:
                dt = datetime.fromisoformat(str(ts_val).replace('Z', '+00:00'))
                return int(dt.timestamp() * 1000)
            except:
                return 0

    def _find_book_uuid(self, conn, ebook_filename):
        cursor = conn.cursor()
        cursor.execute("SELECT uuid, title FROM book")
        results = cursor.fetchall()
        for row in results:
            book_title = row['title']
            if book_title.lower() in ebook_filename.lower():
                return row['uuid'], book_title
        return None, None

    def _update_book_status(self, conn, book_uuid, percentage):
        """Mirror position.ts: Set Reading (<98%) or Read (>=98%)"""
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT uuid, name FROM status WHERE name IN ('Reading', 'Read')")
            statuses = {row['name']: row['uuid'] for row in cursor.fetchall()}
            new_status_uuid = statuses.get('Read') if percentage >= 0.98 else statuses.get('Reading')
            if new_status_uuid:
                cursor.execute("UPDATE bookToStatus SET statusUuid = ? WHERE bookUuid = ?", (new_status_uuid, book_uuid))
        except:
            pass

    def update_progress(self, ebook_filename, percentage, source_timestamp=None):
        """Pushes ABS/KoSync progress INTO Storyteller"""
        try:
            with self._get_connection() as conn:
                book_uuid, book_title = self._find_book_uuid(conn, ebook_filename)
                if not book_uuid: return False

                cursor = conn.cursor()
                cursor.execute("SELECT user_id, locator, updated_at FROM position WHERE book_uuid = ?", (book_uuid,))
                rows = cursor.fetchall()
                if not rows: return False

                base_ts = int((source_timestamp if source_timestamp else time.time()) * 1000)

                for row in rows:
                    current_db_ts = self._parse_timestamp(row['updated_at'])
                    # Leapfrog logic: Ensure we beat the app's internal cache
                    new_ts = max(base_ts, current_db_ts + 60000)

                    locator = json.loads(row['locator'])
                    if 'locations' not in locator: locator['locations'] = {}
                    locator['locations']['totalProgression'] = float(percentage)
                    
                    cursor.execute(
                        "UPDATE position SET locator = ?, updated_at = ? WHERE book_uuid = ? AND user_id = ?",
                        (json.dumps(locator), new_ts, book_uuid, row['user_id'])
                    )
                
                self._update_book_status(conn, book_uuid, percentage)
                logger.info(f"✅ Storyteller Forced Sync: {book_title} to {percentage:.2%}")
                return True
        except Exception as e:
            logger.error(f"Write Error: {e}")
            return False

    def get_progress(self, ebook_filename):
        """REQUIRED BY main.py: Returns (percentage, timestamp)"""
        try:
            with self._get_connection() as conn:
                book_uuid, book_title = self._find_book_uuid(conn, ebook_filename)
                if not book_uuid: 
                    # main.py expects a tuple (None, 0) if not found
                    return None, 0

                cursor = conn.cursor()
                cursor.execute("SELECT locator, updated_at FROM position WHERE book_uuid = ? ORDER BY updated_at DESC LIMIT 1", (book_uuid,))
                row = cursor.fetchone()
                
                if row:
                    locator = json.loads(row['locator'])
                    pct = float(locator.get('locations', {}).get('totalProgression', 0.0))
                    ts = self._parse_timestamp(row['updated_at']) / 1000.0 # To Seconds
                    
                    # Log internally so we don't break main.py's formatters
                    logger.debug(f"Storyteller Progress for {book_title}: {pct:.2%}")
                    
                    return pct, ts
                    
        except Exception as e:
            logger.error(f"Read Error: {e}")
            
        return None, 0

    def get_progress_with_fragment(self, ebook_filename):
        """Returns (percentage, timestamp, href, fragment_id) for precise text extraction
        
        Use this when you need the exact sentence/paragraph location from Storyteller
        for more accurate transcript matching.
        
        Returns:
            tuple: (pct, ts, href, fragment_id) or (None, 0, None, None) if not found
        """
        try:
            with self._get_connection() as conn:
                book_uuid, book_title = self._find_book_uuid(conn, ebook_filename)
                if not book_uuid: 
                    return None, 0, None, None

                cursor = conn.cursor()
                cursor.execute("SELECT locator, updated_at FROM position WHERE book_uuid = ? ORDER BY updated_at DESC LIMIT 1", (book_uuid,))
                row = cursor.fetchone()
                
                if row:
                    locator = json.loads(row['locator'])
                    pct = float(locator.get('locations', {}).get('totalProgression', 0.0))
                    ts = self._parse_timestamp(row['updated_at']) / 1000.0
                    
                    # Extract precise markers for exact text location
                    href = locator.get('href')  # e.g., "OPS/s065-Chapter-048.xhtml"
                    fragments = locator.get('locations', {}).get('fragments', [])
                    fragment_id = fragments[0] if fragments else None  # e.g., "s065-sentence186"
                    
                    logger.debug(f"Storyteller Progress for {book_title}: {pct:.2%}, Fragment: {fragment_id}")
                    
                    return pct, ts, href, fragment_id
                    
        except Exception as e:
            logger.error(f"Read Error: {e}")
            
        return None, 0, None, None
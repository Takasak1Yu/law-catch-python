import sqlite3
import os
import shutil

APP_NAME = "LawCatchCrawler"
APP_DATA_DIR = os.path.join(os.environ.get("APPDATA", ""), APP_NAME)
DB_PATH = os.path.join(APP_DATA_DIR, "crawl_data.db")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OLD_DB_PATH = os.path.join(SCRIPT_DIR, "crawl_data.db")


def ensure_app_data_dir():
    os.makedirs(APP_DATA_DIR, exist_ok=True)


def migrate_from_script_dir():
    if not os.path.exists(OLD_DB_PATH):
        return False
    if os.path.exists(DB_PATH):
        return False
    ensure_app_data_dir()
    shutil.copy2(OLD_DB_PATH, DB_PATH)
    return True


class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        ensure_app_data_dir()
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    first_seen_at TEXT DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(site_key, url)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_site_key
                ON crawl_records(site_key)
            """)

    def get_urls(self, site_key: str) -> set[str]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT url FROM crawl_records WHERE site_key = ?",
                (site_key,),
            )
            return {row[0] for row in cursor.fetchall()}

    def get_records(self, site_key: str) -> list[tuple[str, str]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT title, url FROM crawl_records WHERE site_key = ? ORDER BY first_seen_at DESC",
                (site_key,),
            )
            return cursor.fetchall()

    def insert_records(self, site_key: str, records: list[tuple[str, str]]):
        with sqlite3.connect(self.db_path) as conn:
            for title, url in records:
                conn.execute(
                    "INSERT OR IGNORE INTO crawl_records (site_key, title, url) VALUES (?, ?, ?)",
                    (site_key, title, url),
                )

    def is_initialized(self, site_key: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM crawl_records WHERE site_key = ?",
                (site_key,),
            )
            return cursor.fetchone()[0] > 0

    def get_record_count(self, site_key: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM crawl_records WHERE site_key = ?",
                (site_key,),
            )
            return cursor.fetchone()[0]

    def clear_records(self, site_key: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM crawl_records WHERE site_key = ?",
                (site_key,),
            )

    def delete_latest_record(self, site_key: str) -> tuple[str, str] | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, title, url FROM crawl_records WHERE site_key = ? ORDER BY first_seen_at DESC LIMIT 1",
                (site_key,),
            )
            row = cursor.fetchone()
            if row:
                record_id, title, url = row
                conn.execute("DELETE FROM crawl_records WHERE id = ?", (record_id,))
                return (title, url)
            return None

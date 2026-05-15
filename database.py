import sqlite3
from pathlib import Path

class VideoDatabase:
    def __init__(self, db_path='video_database.db'):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """初始化表结构"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS processed_videos (
                    code TEXT PRIMARY KEY,
                    title TEXT,
                    author TEXT,
                    duration TEXT,
                    size TEXT
                )
            ''')
            conn.commit()

    def save_processed_video(self, code, title, author, duration, size):
        """将一条视频记录保存或更新到数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                REPLACE INTO processed_videos (code, title, author, duration, size)
                VALUES (?, ?, ?, ?, ?)
            ''', (code, title, author, duration, size))
            conn.commit()
import sqlite3
from pathlib import Path

from actor_identifier import IGNORED_ACTOR_NAMES, is_ignored_actor_name


class VideoDatabase:
    def __init__(self, db_path='video_database.db'):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """初始化表结构（以 code 为主键实现绝对去重）"""
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
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actors (
                    name TEXT PRIMARY KEY,
                    birthday TEXT,
                    age TEXT,
                    matched INTEGER DEFAULT 0
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS path_library (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.executemany(
                'DELETE FROM actors WHERE lower(name) = ?',
                [(name,) for name in IGNORED_ACTOR_NAMES],
            )
            conn.commit()

    def save_plans(self, plans):
        """将扫描到的计划列表批量写入/更新到数据库"""
        if not plans:
            return 0

        success_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for plan in plans:
                cursor.execute('''
                    REPLACE INTO processed_videos (code, title, author, duration, size)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    plan.metadata.code,
                    plan.metadata.title,
                    plan.metadata.author,
                    plan.metadata.duration,
                    plan.metadata.size
                ))
                success_count += 1
            conn.commit()

        return success_count

    def save_actors(self, actors):
        """将识别出的演员单独写入演员表。"""
        if not actors:
            return 0

        success_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for actor in actors:
                name = actor.get('name', '').strip()
                if not name or is_ignored_actor_name(name):
                    continue

                cursor.execute('''
                    REPLACE INTO actors (name, birthday, age, matched)
                    VALUES (?, ?, ?, ?)
                ''', (
                    name,
                    actor.get('birthday', ''),
                    actor.get('age', ''),
                    1 if actor.get('matched') else 0,
                ))
                success_count += 1
            conn.commit()

        return success_count

    def list_actors(self, search_text=''):
        """读取演员库，必要时按主角/生日/年龄筛选。"""
        search_text = (search_text or '').strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if search_text:
                like_value = f'%{search_text}%'
                cursor.execute('''
                    SELECT name, birthday, age, matched
                    FROM actors
                    WHERE name LIKE ? OR birthday LIKE ? OR age LIKE ?
                    ORDER BY name
                ''', (like_value, like_value, like_value))
            else:
                cursor.execute('''
                    SELECT name, birthday, age, matched
                    FROM actors
                    ORDER BY name
                ''')

            return [
                {
                    'name': row[0] or '',
                    'birthday': row[1] or '',
                    'age': row[2] or '',
                    'matched': bool(row[3]),
                }
                for row in cursor.fetchall()
                if not is_ignored_actor_name(row[0] or '')
            ]

    def list_videos(self, search_text=''):
        """读取数据库台账，必要时按编号/标题/演员筛选。"""
        search_text = (search_text or '').strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if search_text:
                like_value = f'%{search_text}%'
                cursor.execute('''
                    SELECT code, title, author, duration, size
                    FROM processed_videos
                    WHERE code LIKE ? OR title LIKE ? OR author LIKE ?
                    ORDER BY code
                ''', (like_value, like_value, like_value))
            else:
                cursor.execute('''
                    SELECT code, title, author, duration, size
                    FROM processed_videos
                    ORDER BY code
                ''')

            return [
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': row[2] or '',
                    'duration': row[3] or '',
                    'size': row[4] or '',
                }
                for row in cursor.fetchall()
            ]

    def add_path(self, folder_path):
        """写入一个路径库记录，已存在时保持一条记录。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO path_library (path)
                VALUES (?)
            ''', (folder_path,))
            conn.commit()

        return self.get_path_by_value(folder_path)

    def delete_path(self, path_id):
        """按 id 删除路径库记录。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM path_library WHERE id = ?', (path_id,))
            conn.commit()
            return cursor.rowcount

    def list_paths(self):
        """读取路径库。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, path, created_at
                FROM path_library
                ORDER BY created_at DESC, id DESC
            ''')

            return [
                {
                    'id': row[0],
                    'path': row[1] or '',
                    'created_at': row[2] or '',
                }
                for row in cursor.fetchall()
            ]

    def get_path_by_value(self, folder_path):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, path, created_at
                FROM path_library
                WHERE path = ?
            ''', (folder_path,))
            row = cursor.fetchone()

        if not row:
            return None

        return {
            'id': row[0],
            'path': row[1] or '',
            'created_at': row[2] or '',
        }

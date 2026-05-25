import sqlite3
from datetime import datetime
from pathlib import Path

from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.core.enrichment_sources import (
    AVFAN_VIDEO_SOURCE,
    DEFAULT_VIDEO_ENRICHMENT_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    build_library_enrichment_status_text,
    build_video_enrichment_status_text,
    is_effective_video_pending_status,
    normalize_video_enrichment_source,
)
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.core.project_paths import DATABASE_FILE
from app.services.actor_identifier import IGNORED_ACTOR_NAMES, is_ignored_actor_name
from app.services.movie_author_resolver import JAVTXT_AUTHOR_MIN_RELEASE_DATE


def join_values(value):
    if isinstance(value, (list, tuple)):
        return ' '.join(str(item) for item in value if str(item).strip())
    return str(value or '')


def sanitize_actor_text(value):
    return normalize_second_source_actor_text(value)


class VideoDatabase:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DATABASE_FILE
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=60)
        conn.execute('PRAGMA busy_timeout = 60000')
        return conn

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
                    size TEXT,
                    storage_location TEXT,
                    avfan_movie_id TEXT,
                    release_date TEXT,
                    maker TEXT,
                    publisher TEXT,
                    enrichment_status TEXT DEFAULT '未补全',
                    enrichment_error TEXT,
                    enriched_at TEXT
                )
            ''')
            self._ensure_column(cursor, 'processed_videos', 'storage_location', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'avfan_movie_id', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_movie_id', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_url', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_title', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_actors', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'maker', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'publisher', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'enrichment_status', "TEXT DEFAULT '未补全'")
            self._ensure_column(cursor, 'processed_videos', 'enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'enriched_at', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'avfan_enrichment_status', "TEXT DEFAULT '未补全'")
            self._ensure_column(cursor, 'processed_videos', 'avfan_enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'avfan_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_enrichment_status', "TEXT DEFAULT '未补全'")
            self._ensure_column(cursor, 'processed_videos', 'javtxt_enrichment_error', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_enriched_at', 'TEXT')
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = '未补全'
                WHERE enrichment_status IS NULL OR enrichment_status = ''
            ''')
            cursor.execute('''
                UPDATE processed_videos
                SET avfan_enrichment_status = COALESCE(NULLIF(avfan_enrichment_status, ''), COALESCE(NULLIF(enrichment_status, ''), ?))
            ''', (UNENRICHED_STATUS,))
            cursor.execute('''
                UPDATE processed_videos
                SET javtxt_enrichment_status = COALESCE(NULLIF(javtxt_enrichment_status, ''), ?)
            ''', (UNENRICHED_STATUS,))
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_total_bytes INTEGER DEFAULT 0,
                    last_used_bytes INTEGER DEFAULT 0,
                    last_free_bytes INTEGER DEFAULT 0,
                    last_usage_percent REAL DEFAULT 0,
                    last_volume_type TEXT DEFAULT '',
                    last_checked_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS code_prefix_enrichments (
                    prefix TEXT PRIMARY KEY,
                    enrichment_status TEXT DEFAULT '',
                    avfan_total_pages INTEGER DEFAULT 0,
                    avfan_total_videos INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    last_enriched_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS code_prefix_movies (
                    prefix TEXT NOT NULL,
                    code TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    release_date TEXT,
                    avfan_url TEXT,
                    page_number INTEGER DEFAULT 1,
                    PRIMARY KEY (prefix, code)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actor_enrichments (
                    actor_name TEXT PRIMARY KEY,
                    actor_id TEXT DEFAULT '',
                    enrichment_status TEXT DEFAULT '',
                    avfan_total_pages INTEGER DEFAULT 0,
                    avfan_total_videos INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    last_enriched_at TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS actor_movies (
                    actor_name TEXT NOT NULL,
                    code TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    release_date TEXT,
                    avfan_url TEXT,
                    page_number INTEGER DEFAULT 1,
                    PRIMARY KEY (actor_name, code)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS hidden_code_prefixes (
                    prefix TEXT PRIMARY KEY
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS hidden_actors (
                    name TEXT PRIMARY KEY
                )
            ''')
            self._ensure_column(cursor, 'path_library', 'last_total_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_used_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_free_bytes', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_usage_percent', 'REAL DEFAULT 0')
            self._ensure_column(cursor, 'path_library', 'last_volume_type', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'path_library', 'last_checked_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_total_pages', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'avfan_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'javtxt_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'javtxt_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'javtxt_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_enrichments', 'javtxt_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'title', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'author', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'avfan_url', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'page_number', 'INTEGER DEFAULT 1')
            self._ensure_column(cursor, 'actor_enrichments', 'actor_id', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_total_pages', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'actor_enrichments', 'last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'avfan_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_enrichments', 'javtxt_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'javtxt_total_videos', 'INTEGER DEFAULT 0')
            self._ensure_column(cursor, 'actor_enrichments', 'javtxt_last_error', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_enrichments', 'javtxt_last_enriched_at', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'title', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'author', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'release_date', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'avfan_url', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'page_number', 'INTEGER DEFAULT 1')
            cursor.execute(
                '''
                UPDATE code_prefix_enrichments
                SET avfan_enrichment_status = COALESCE(NULLIF(avfan_enrichment_status, ''), COALESCE(NULLIF(enrichment_status, ''), ?)),
                    avfan_last_error = COALESCE(NULLIF(avfan_last_error, ''), COALESCE(NULLIF(last_error, ''), '')),
                    avfan_last_enriched_at = COALESCE(NULLIF(avfan_last_enriched_at, ''), last_enriched_at),
                    javtxt_enrichment_status = COALESCE(NULLIF(javtxt_enrichment_status, ''), ?),
                    javtxt_total_videos = COALESCE(javtxt_total_videos, 0)
                ''',
                (UNENRICHED_STATUS, UNENRICHED_STATUS),
            )
            cursor.execute(
                '''
                UPDATE actor_enrichments
                SET avfan_enrichment_status = COALESCE(NULLIF(avfan_enrichment_status, ''), COALESCE(NULLIF(enrichment_status, ''), ?)),
                    avfan_last_error = COALESCE(NULLIF(avfan_last_error, ''), COALESCE(NULLIF(last_error, ''), '')),
                    avfan_last_enriched_at = COALESCE(NULLIF(avfan_last_enriched_at, ''), last_enriched_at),
                    javtxt_enrichment_status = COALESCE(NULLIF(javtxt_enrichment_status, ''), ?),
                    javtxt_total_videos = COALESCE(javtxt_total_videos, 0)
                ''',
                (UNENRICHED_STATUS, UNENRICHED_STATUS),
            )
            cursor.executemany(
                'DELETE FROM actors WHERE lower(name) = ?',
                [(name,) for name in IGNORED_ACTOR_NAMES],
            )
            conn.commit()

    def _ensure_column(self, cursor, table_name, column_name, column_type):
        cursor.execute(f'PRAGMA table_info({table_name})')
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name not in existing_columns:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}')

    def _video_source_columns(self, source_key):
        normalized_source = normalize_video_enrichment_source(source_key)
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            return 'javtxt_enrichment_status', 'javtxt_enrichment_error', 'javtxt_enriched_at'
        return 'avfan_enrichment_status', 'avfan_enrichment_error', 'avfan_enriched_at'

    def _library_source_columns(self, source_key):
        normalized_source = normalize_video_enrichment_source(source_key)
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            return 'javtxt_enrichment_status', 'javtxt_last_error', 'javtxt_last_enriched_at'
        return 'avfan_enrichment_status', 'avfan_last_error', 'avfan_last_enriched_at'

    def save_plans(self, plans):
        """将扫描到的计划列表批量写入/更新到数据库"""
        if not plans:
            return 0

        success_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for plan in plans:
                cursor.execute('''
                    INSERT INTO processed_videos (
                        code, title, author, duration, size, storage_location, enrichment_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, '未补全')
                    ON CONFLICT(code) DO UPDATE SET
                        title = excluded.title,
                        author = excluded.author,
                        duration = excluded.duration,
                        size = excluded.size,
                        storage_location = excluded.storage_location,
                        enrichment_status = COALESCE(NULLIF(processed_videos.enrichment_status, ''), '未补全')
                ''', (
                    plan.metadata.code,
                    plan.metadata.title,
                    plan.metadata.author,
                    plan.metadata.duration,
                    plan.metadata.size,
                    plan.storage_location
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
        """读取演员库，必要时按演员/生日/年龄/补全状态筛选。"""
        search_text = (search_text or '').strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if search_text:
                like_value = f'%{search_text}%'
                cursor.execute('''
                    SELECT a.name, a.birthday, a.age, a.matched,
                           COALESCE(e.actor_id, '') AS actor_id,
                           COALESCE(e.enrichment_status, ?) AS enrichment_status
                    FROM actors a
                    LEFT JOIN actor_enrichments e ON e.actor_name = a.name
                    WHERE a.name LIKE ? OR a.birthday LIKE ? OR a.age LIKE ?
                       OR COALESCE(e.actor_id, '') LIKE ?
                       OR COALESCE(e.enrichment_status, ?) LIKE ?
                    ORDER BY a.name
                ''', (
                    UNENRICHED_STATUS,
                    like_value,
                    like_value,
                    like_value,
                    like_value,
                    UNENRICHED_STATUS,
                    like_value,
                ))
            else:
                cursor.execute('''
                    SELECT a.name, a.birthday, a.age, a.matched,
                           COALESCE(e.actor_id, '') AS actor_id,
                           COALESCE(e.enrichment_status, ?) AS enrichment_status
                    FROM actors a
                    LEFT JOIN actor_enrichments e ON e.actor_name = a.name
                    ORDER BY a.name
                ''', (UNENRICHED_STATUS,))

            rows = cursor.fetchall()

        enrichment_records = self.list_actor_enrichment_records()
        results = []
        for row in rows:
            actor_name = row[0] or ''
            if is_ignored_actor_name(actor_name):
                continue
            record = enrichment_records.get(actor_name, {})
            results.append(
                {
                    'name': actor_name,
                    'birthday': row[1] or '',
                    'age': row[2] or '',
                    'matched': bool(row[3]),
                    'actor_id': row[4] or '',
                    'enrichment_status': self._build_live_actor_enrichment_status(
                        record,
                        self.list_actor_movies(actor_name),
                    ),
                }
            )
        return results

    def list_videos(self, search_text=''):
        """读取数据库台账，必要时按编号/标题/演员筛选。"""
        search_text = (search_text or '').strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if search_text:
                like_value = f'%{search_text}%'
                cursor.execute('''
                    SELECT code, title, author, duration, size, storage_location,
                           avfan_movie_id, release_date, maker, publisher, enrichment_status
                    FROM processed_videos
                    WHERE code LIKE ? OR title LIKE ? OR author LIKE ? OR storage_location LIKE ?
                       OR avfan_movie_id LIKE ? OR release_date LIKE ? OR maker LIKE ? OR publisher LIKE ?
                       OR enrichment_status LIKE ?
                    ORDER BY code
                ''', (
                    like_value, like_value, like_value, like_value, like_value,
                    like_value, like_value, like_value, like_value,
                ))
            else:
                cursor.execute('''
                    SELECT code, title, author, duration, size, storage_location,
                           avfan_movie_id, release_date, maker, publisher, enrichment_status
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
                    'storage_location': row[5] or '',
                    'avfan_movie_id': row[6] or '',
                    'release_date': row[7] or '',
                    'maker': row[8] or '',
                    'publisher': row[9] or '',
                    'enrichment_status': row[10] or '未补全',
                }
                for row in cursor.fetchall()
            ]

    def list_videos_for_enrichment(self, limit):
        """读取需要补全的未补全视频。"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT code, title, author
                FROM processed_videos
                WHERE COALESCE(enrichment_status, '未补全') != '已补全'
                ORDER BY code
                LIMIT ?
            ''', (int(limit),))

            return [
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': row[2] or '',
                }
                for row in cursor.fetchall()
            ]

    def update_video_enrichment(self, code, info, status='已补全'):
        """写入网页补全信息。"""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('''
                UPDATE processed_videos
                SET avfan_movie_id = ?,
                    release_date = ?,
                    maker = ?,
                    publisher = ?,
                    enrichment_status = ?,
                    enrichment_error = ?,
                    enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
            ''', (
                info.get('avfan_movie_id', ''),
                info.get('release_date', ''),
                join_values(info.get('maker')),
                join_values(info.get('publisher')),
                status,
                info.get('error', ''),
                code,
            ))
            conn.commit()

    def mark_video_enrichment_failed(self, code, error):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = '补全失败',
                    enrichment_error = ?,
                    enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
            ''', (error, code))
            conn.commit()

    def count_videos_by_enrichment_status(self, status):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*)
                FROM processed_videos
                WHERE COALESCE(enrichment_status, '未补全') = ?
            ''', (status,))
            return int(cursor.fetchone()[0] or 0)

    def get_video_enrichment_summary(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COUNT(*) AS total_count,
                    SUM(
                        CASE
                            WHEN COALESCE(enrichment_status, '鏈ˉ鍏?) = '宸茶ˉ鍏? THEN 1
                            ELSE 0
                        END
                    ) AS enriched_count
                FROM processed_videos
            ''')
            row = cursor.fetchone() or (0, 0)

        total_count = int(row[0] or 0)
        enriched_count = int(row[1] or 0)
        unenriched_count = max(total_count - enriched_count, 0)
        return {
            'enriched_count': enriched_count,
            'unenriched_count': unenriched_count,
            'total_count': total_count,
        }

    def _refresh_code_prefix_combined_status(self, cursor, prefix):
        cursor.execute(
            '''
            SELECT avfan_enrichment_status, javtxt_enrichment_status,
                   avfan_last_error, javtxt_last_error,
                   avfan_last_enriched_at, javtxt_last_enriched_at
            FROM code_prefix_enrichments
            WHERE prefix = ?
            ''',
            (prefix,),
        )
        row = cursor.fetchone() or (
            UNENRICHED_STATUS,
            UNENRICHED_STATUS,
            '',
            '',
            '',
            '',
        )
        avfan_status, javtxt_status, avfan_error, javtxt_error, avfan_at, javtxt_at = row
        combined_status = build_library_enrichment_status_text(avfan_status, javtxt_status)
        latest_error = str(javtxt_error or avfan_error or '')
        latest_at = str(javtxt_at or avfan_at or '')
        cursor.execute(
            '''
            UPDATE code_prefix_enrichments
            SET enrichment_status = ?,
                last_error = ?,
                last_enriched_at = ?
            WHERE prefix = ?
            ''',
            (combined_status, latest_error, latest_at, prefix),
        )

    def _refresh_actor_combined_status(self, cursor, actor_name):
        cursor.execute(
            '''
            SELECT avfan_enrichment_status, javtxt_enrichment_status,
                   avfan_last_error, javtxt_last_error,
                   avfan_last_enriched_at, javtxt_last_enriched_at
            FROM actor_enrichments
            WHERE actor_name = ?
            ''',
            (actor_name,),
        )
        row = cursor.fetchone() or (
            UNENRICHED_STATUS,
            UNENRICHED_STATUS,
            '',
            '',
            '',
            '',
        )
        avfan_status, javtxt_status, avfan_error, javtxt_error, avfan_at, javtxt_at = row
        combined_status = build_library_enrichment_status_text(avfan_status, javtxt_status)
        latest_error = str(javtxt_error or avfan_error or '')
        latest_at = str(javtxt_at or avfan_at or '')
        cursor.execute(
            '''
            UPDATE actor_enrichments
            SET enrichment_status = ?,
                last_error = ?,
                last_enriched_at = ?
            WHERE actor_name = ?
            ''',
            (combined_status, latest_error, latest_at, actor_name),
        )

    def _build_live_actor_enrichment_status(self, enrichment, movies):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '') or '').strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '') or '').strip() or UNENRICHED_STATUS

        eligible_movies = [movie for movie in (movies or []) if self._is_javtxt_eligible_movie(movie)]
        if eligible_movies and all(
            normalize_second_source_actor_text((movie or {}).get('author', ''))
            for movie in eligible_movies
        ):
            javtxt_status = ENRICHED_STATUS
        else:
            javtxt_status = str((enrichment or {}).get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS

        return build_library_enrichment_status_text(avfan_status, javtxt_status)

    @staticmethod
    def _is_javtxt_eligible_movie(movie):
        release_date_text = str((movie or {}).get('release_date', '') or '').strip()
        if not release_date_text:
            return False
        try:
            release_date = datetime.strptime(release_date_text, '%Y-%m-%d').date()
        except ValueError:
            return False
        return release_date >= JAVTXT_AUTHOR_MIN_RELEASE_DATE

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
                SELECT id, path, created_at, last_total_bytes, last_used_bytes,
                       last_free_bytes, last_usage_percent, last_volume_type, last_checked_at
                FROM path_library
                ORDER BY created_at DESC, id DESC
            ''')

            return [
                {
                    'id': row[0],
                    'path': row[1] or '',
                    'created_at': row[2] or '',
                    'last_total_bytes': row[3] or 0,
                    'last_used_bytes': row[4] or 0,
                    'last_free_bytes': row[5] or 0,
                    'last_usage_percent': row[6] or 0,
                    'last_volume_type': row[7] or '',
                    'last_checked_at': row[8] or '',
                }
                for row in cursor.fetchall()
            ]

    def update_path_storage_info(self, path_id, storage_info):
        """保存路径最后一次成功检测到的容量快照。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE path_library
                SET last_total_bytes = ?,
                    last_used_bytes = ?,
                    last_free_bytes = ?,
                    last_usage_percent = ?,
                    last_volume_type = ?,
                    last_checked_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                storage_info.get('total_bytes', 0),
                storage_info.get('used_bytes', 0),
                storage_info.get('free_bytes', 0),
                storage_info.get('usage_percent', 0),
                storage_info.get('volume_type', ''),
                path_id,
            ))
            conn.commit()

    def list_videos_for_enrichment(self, limit):
        """只返回仍应继续补全的视频，跳过已补全和无搜索结果。"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT code, title, author
                FROM processed_videos
                WHERE COALESCE(enrichment_status, ?) IN (?, ?)
                ORDER BY code
                LIMIT ?
            ''', (
                UNENRICHED_STATUS,
                UNENRICHED_STATUS,
                FAILED_STATUS,
                int(limit),
            ))

            return [
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': row[2] or '',
                }
                for row in cursor.fetchall()
            ]

    def mark_video_no_search_results(self, code, error='未搜索到匹配影片'):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = ?,
                    enrichment_error = ?,
                    enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
            ''', (NO_SEARCH_RESULTS_STATUS, error, code))
            conn.commit()

    def mark_video_enrichment_failed(self, code, error):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE processed_videos
                SET enrichment_status = ?,
                    enrichment_error = ?,
                    enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
            ''', (FAILED_STATUS, error, code))
            conn.commit()

    def count_videos_by_enrichment_status(self, status):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*)
                FROM processed_videos
                WHERE COALESCE(enrichment_status, ?) = ?
            ''', (UNENRICHED_STATUS, status))
            return int(cursor.fetchone()[0] or 0)

    def get_video_enrichment_summary(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COUNT(*) AS total_count,
                    SUM(
                        CASE
                            WHEN COALESCE(enrichment_status, ?) = ? THEN 1
                            ELSE 0
                        END
                    ) AS enriched_count
                FROM processed_videos
            ''', (UNENRICHED_STATUS, ENRICHED_STATUS))
            row = cursor.fetchone() or (0, 0)

        total_count = int(row[0] or 0)
        enriched_count = int(row[1] or 0)
        unenriched_count = max(total_count - enriched_count, 0)
        return {
            'enriched_count': enriched_count,
            'unenriched_count': unenriched_count,
            'total_count': total_count,
        }

    def list_code_prefix_enrichment_records(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT prefix, enrichment_status, avfan_total_pages, avfan_total_videos,
                       last_error, last_enriched_at, avfan_enrichment_status, avfan_last_error,
                       avfan_last_enriched_at, javtxt_enrichment_status, javtxt_total_videos,
                       javtxt_last_error, javtxt_last_enriched_at
                FROM code_prefix_enrichments
            ''')

            return {
                (row[0] or ''): {
                    'prefix': row[0] or '',
                    'enrichment_status': row[1] or '',
                    'avfan_total_pages': int(row[2] or 0),
                    'avfan_total_videos': int(row[3] or 0),
                    'last_error': row[4] or '',
                    'last_enriched_at': row[5] or '',
                    'avfan_enrichment_status': row[6] or UNENRICHED_STATUS,
                    'avfan_last_error': row[7] or '',
                    'avfan_last_enriched_at': row[8] or '',
                    'javtxt_enrichment_status': row[9] or UNENRICHED_STATUS,
                    'javtxt_total_videos': int(row[10] or 0),
                    'javtxt_last_error': row[11] or '',
                    'javtxt_last_enriched_at': row[12] or '',
                }
                for row in cursor.fetchall()
                if row[0]
            }

    def list_hidden_code_prefixes(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT prefix FROM hidden_code_prefixes ORDER BY prefix')
            return {
                str(row[0] or '').strip().upper()
                for row in cursor.fetchall()
                if str(row[0] or '').strip()
            }

    def save_code_prefix_enrichment(self, prefix, status, total_pages=0, total_videos=0, error='', source_key=AVFAN_VIDEO_SOURCE):
        normalized_prefix = str(prefix or '').strip().upper()
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, error_column, at_column = self._library_source_columns(normalized_source)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO code_prefix_enrichments (prefix)
                VALUES (?)
                ''',
                (normalized_prefix,),
            )
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE code_prefix_enrichments
                    SET {status_column} = ?,
                        javtxt_total_videos = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE prefix = ?
                    ''',
                    (
                        status,
                        int(total_videos or 0),
                        str(error or ''),
                        normalized_prefix,
                    ),
                )
            else:
                cursor.execute(
                    f'''
                    UPDATE code_prefix_enrichments
                    SET {status_column} = ?,
                        avfan_total_pages = ?,
                        avfan_total_videos = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE prefix = ?
                    ''',
                    (
                        status,
                        int(total_pages or 0),
                        int(total_videos or 0),
                        str(error or ''),
                        normalized_prefix,
                    ),
                )
            self._refresh_code_prefix_combined_status(cursor, normalized_prefix)
            conn.commit()

    def replace_code_prefix_movies(self, prefix, movies):
        prefix = str(prefix or '').strip().upper()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM code_prefix_movies WHERE prefix = ?', (prefix,))
            if movies:
                cursor.executemany('''
                    INSERT OR REPLACE INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', [
                    (
                        prefix,
                        str(movie.get('code', '')).strip().upper(),
                        movie.get('title', ''),
                        sanitize_actor_text(movie.get('author', '')),
                        movie.get('release_date', ''),
                        movie.get('avfan_url', ''),
                        int(movie.get('page_number', 1) or 1),
                    )
                    for movie in movies
                    if movie.get('code')
                ])
            conn.commit()

    def get_code_prefix_enrichment_record(self, prefix):
        prefix = str(prefix or '').strip().upper()
        records = self.list_code_prefix_enrichment_records()
        return records.get(prefix, {
            'prefix': prefix,
            'enrichment_status': '',
            'avfan_total_pages': 0,
            'avfan_total_videos': 0,
            'last_error': '',
            'last_enriched_at': '',
            'avfan_enrichment_status': UNENRICHED_STATUS,
            'avfan_last_error': '',
            'avfan_last_enriched_at': '',
            'javtxt_enrichment_status': UNENRICHED_STATUS,
            'javtxt_total_videos': 0,
            'javtxt_last_error': '',
            'javtxt_last_enriched_at': '',
        })

    def list_code_prefix_movies(self, prefix):
        prefix = str(prefix or '').strip().upper()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT prefix, code, title, author, release_date, avfan_url, page_number
                FROM code_prefix_movies
                WHERE prefix = ?
                ORDER BY release_date DESC, code DESC
            ''', (prefix,))

            return [
                {
                    'prefix': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': sanitize_actor_text(row[3] or ''),
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                }
                for row in cursor.fetchall()
            ]

    def list_actor_enrichment_records(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT actor_name, actor_id, enrichment_status, avfan_total_pages, avfan_total_videos,
                       last_error, last_enriched_at, avfan_enrichment_status, avfan_last_error,
                       avfan_last_enriched_at, javtxt_enrichment_status, javtxt_total_videos,
                       javtxt_last_error, javtxt_last_enriched_at
                FROM actor_enrichments
            ''')

            return {
                (row[0] or ''): {
                    'actor_name': row[0] or '',
                    'actor_id': row[1] or '',
                    'enrichment_status': row[2] or '',
                    'avfan_total_pages': int(row[3] or 0),
                    'avfan_total_videos': int(row[4] or 0),
                    'last_error': row[5] or '',
                    'last_enriched_at': row[6] or '',
                    'avfan_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'avfan_last_error': row[8] or '',
                    'avfan_last_enriched_at': row[9] or '',
                    'javtxt_enrichment_status': row[10] or UNENRICHED_STATUS,
                    'javtxt_total_videos': int(row[11] or 0),
                    'javtxt_last_error': row[12] or '',
                    'javtxt_last_enriched_at': row[13] or '',
                }
                for row in cursor.fetchall()
                if row[0]
            }

    def save_actor_enrichment(self, actor_name, status, total_pages=0, total_videos=0, error='', actor_id='', source_key=AVFAN_VIDEO_SOURCE):
        normalized_name = str(actor_name or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, error_column, at_column = self._library_source_columns(normalized_source)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO actor_enrichments (actor_name, actor_id)
                VALUES (?, ?)
                ''',
                (normalized_name, str(actor_id or '').strip()),
            )
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE actor_enrichments
                    SET {status_column} = ?,
                        javtxt_total_videos = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE actor_name = ?
                    ''',
                    (
                        status,
                        int(total_videos or 0),
                        str(error or ''),
                        normalized_name,
                    ),
                )
            else:
                cursor.execute(
                    f'''
                    UPDATE actor_enrichments
                    SET actor_id = COALESCE(NULLIF(?, ''), actor_id),
                        {status_column} = ?,
                        avfan_total_pages = ?,
                        avfan_total_videos = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE actor_name = ?
                    ''',
                    (
                        str(actor_id or '').strip(),
                        status,
                        int(total_pages or 0),
                        int(total_videos or 0),
                        str(error or ''),
                        normalized_name,
                    ),
                )
            self._refresh_actor_combined_status(cursor, normalized_name)
            conn.commit()

    def replace_actor_movies(self, actor_name, movies):
        normalized_name = str(actor_name or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM actor_movies WHERE actor_name = ?', (normalized_name,))
            if movies:
                cursor.executemany('''
                    INSERT OR REPLACE INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', [
                    (
                        normalized_name,
                        str(movie.get('code', '')).strip().upper(),
                        movie.get('title', ''),
                        sanitize_actor_text(movie.get('author', '')),
                        movie.get('release_date', ''),
                        movie.get('avfan_url', ''),
                        int(movie.get('page_number', 1) or 1),
                    )
                    for movie in movies
                    if movie.get('code')
                ])
            conn.commit()

    def get_actor_enrichment_record(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        records = self.list_actor_enrichment_records()
        return records.get(normalized_name, {
            'actor_name': normalized_name,
            'actor_id': '',
            'enrichment_status': '',
            'avfan_total_pages': 0,
            'avfan_total_videos': 0,
            'last_error': '',
            'last_enriched_at': '',
            'avfan_enrichment_status': UNENRICHED_STATUS,
            'avfan_last_error': '',
            'avfan_last_enriched_at': '',
            'javtxt_enrichment_status': UNENRICHED_STATUS,
            'javtxt_total_videos': 0,
            'javtxt_last_error': '',
            'javtxt_last_enriched_at': '',
        })

    def list_actor_movies(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT actor_name, code, title, author, release_date, avfan_url, page_number
                FROM actor_movies
                WHERE actor_name = ?
                ORDER BY release_date DESC, code DESC
            ''', (normalized_name,))

            return [
                {
                    'actor_name': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': sanitize_actor_text(row[3] or ''),
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                }
                for row in cursor.fetchall()
            ]

    def reset_video_enrichments(self, codes):
        normalized_codes = [
            str(code or '').strip().upper()
            for code in (codes or [])
            if str(code or '').strip()
        ]
        if not normalized_codes:
            return 0

        placeholders = ','.join('?' for _ in normalized_codes)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE processed_videos
                SET avfan_movie_id = '',
                    release_date = '',
                    maker = '',
                    publisher = '',
                    enrichment_status = ?,
                    enrichment_error = '',
                    enriched_at = NULL
                WHERE code IN ({placeholders})
            ''', [UNENRICHED_STATUS, *normalized_codes])
            conn.commit()
            return int(cursor.rowcount or 0)

    def reset_actor_enrichments(self, actor_names):
        normalized_names = [
            str(actor_name or '').strip()
            for actor_name in (actor_names or [])
            if str(actor_name or '').strip()
        ]
        if not normalized_names:
            return 0

        placeholders = ','.join('?' for _ in normalized_names)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                DELETE FROM actor_movies
                WHERE actor_name IN ({placeholders})
            ''', normalized_names)
            cursor.execute(f'''
                DELETE FROM actor_enrichments
                WHERE actor_name IN ({placeholders})
            ''', normalized_names)
            conn.commit()
            return len(normalized_names)

    def rename_actor(self, old_name, new_name, author_updates=None):
        normalized_old_name = str(old_name or '').strip()
        normalized_new_name = str(new_name or '').strip()
        updates = list(author_updates or [])
        if not normalized_old_name or not normalized_new_name:
            raise ValueError('演员名称不能为空')

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1 FROM actors WHERE name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 已存在')

            cursor.execute('SELECT 1 FROM actor_enrichments WHERE actor_name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 的补全记录已存在')

            cursor.execute('SELECT 1 FROM actor_movies WHERE actor_name = ?', (normalized_new_name,))
            if normalized_old_name != normalized_new_name and cursor.fetchone():
                raise ValueError(f'演员 {normalized_new_name} 的作品记录已存在')

            cursor.execute(
                'UPDATE actors SET name = ? WHERE name = ?',
                (normalized_new_name, normalized_old_name),
            )
            updated_actor_count = int(cursor.rowcount or 0)

            cursor.execute(
                'UPDATE actor_enrichments SET actor_name = ? WHERE actor_name = ?',
                (normalized_new_name, normalized_old_name),
            )
            cursor.execute(
                'UPDATE actor_movies SET actor_name = ? WHERE actor_name = ?',
                (normalized_new_name, normalized_old_name),
            )

            for update in updates:
                code = str(update.get('code', '')).strip().upper()
                author = str(update.get('author', '')).strip()
                if not code:
                    continue
                cursor.execute(
                    'UPDATE processed_videos SET author = ? WHERE code = ?',
                    (author, code),
                )

            conn.commit()
            return updated_actor_count

    def delete_actor(self, actor_name):
        normalized_name = str(actor_name or '').strip()
        if not normalized_name:
            raise ValueError('演员名称不能为空')

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM actor_movies WHERE actor_name = ?', (normalized_name,))
            cursor.execute('DELETE FROM actor_enrichments WHERE actor_name = ?', (normalized_name,))
            cursor.execute('DELETE FROM actors WHERE name = ?', (normalized_name,))
            cursor.execute(
                'INSERT OR IGNORE INTO hidden_actors (name) VALUES (?)',
                (normalized_name,),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def reset_code_prefix_enrichments(self, prefixes):
        normalized_prefixes = [
            str(prefix or '').strip().upper()
            for prefix in (prefixes or [])
            if str(prefix or '').strip()
        ]
        if not normalized_prefixes:
            return 0

        placeholders = ','.join('?' for _ in normalized_prefixes)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                DELETE FROM code_prefix_movies
                WHERE prefix IN ({placeholders})
            ''', normalized_prefixes)
            cursor.execute(f'''
                DELETE FROM code_prefix_enrichments
                WHERE prefix IN ({placeholders})
            ''', normalized_prefixes)
            conn.commit()
            return len(normalized_prefixes)

    def rename_code_prefix(self, old_prefix, new_prefix, code_updates=None, web_movie_updates=None):
        normalized_old_prefix = str(old_prefix or '').strip().upper()
        normalized_new_prefix = str(new_prefix or '').strip().upper()
        normalized_code_updates = [
            (
                str(old_code or '').strip().upper(),
                str(new_code or '').strip().upper(),
            )
            for old_code, new_code in (code_updates or [])
            if str(old_code or '').strip() and str(new_code or '').strip()
        ]
        normalized_web_movie_updates = [
            (
                str(old_code or '').strip().upper(),
                str(new_code or '').strip().upper(),
            )
            for old_code, new_code in (web_movie_updates or [])
            if str(old_code or '').strip() and str(new_code or '').strip()
        ]

        if not normalized_old_prefix or not normalized_new_prefix:
            raise ValueError('番号前缀不能为空')

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if normalized_old_prefix != normalized_new_prefix:
                cursor.execute('SELECT 1 FROM code_prefix_enrichments WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在补全记录')

                cursor.execute('SELECT 1 FROM code_prefix_movies WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在网页作品记录')

                cursor.execute('SELECT 1 FROM hidden_code_prefixes WHERE prefix = ?', (normalized_new_prefix,))
                if cursor.fetchone():
                    raise ValueError(f'番号前缀 {normalized_new_prefix} 已被删除，请换一个前缀名称')

            if normalized_code_updates:
                old_codes = [item[0] for item in normalized_code_updates]
                new_codes = [item[1] for item in normalized_code_updates]
                if len(set(new_codes)) != len(new_codes):
                    raise ValueError('新番号中存在重复值，无法修改前缀')

                new_placeholders = ','.join('?' for _ in new_codes)
                old_placeholders = ','.join('?' for _ in old_codes)
                cursor.execute(
                    f'''
                    SELECT code
                    FROM processed_videos
                    WHERE code IN ({new_placeholders})
                      AND code NOT IN ({old_placeholders})
                    ''',
                    [*new_codes, *old_codes],
                )
                collision_rows = [row[0] for row in cursor.fetchall() if row[0]]
                if collision_rows:
                    raise ValueError(f'目标番号已存在：{collision_rows[0]}')

            for old_code, new_code in normalized_code_updates:
                cursor.execute(
                    'UPDATE processed_videos SET code = ? WHERE code = ?',
                    (new_code, old_code),
                )

            for old_code, new_code in normalized_web_movie_updates:
                cursor.execute(
                    '''
                    UPDATE code_prefix_movies
                    SET prefix = ?, code = ?
                    WHERE prefix = ? AND code = ?
                    ''',
                    (normalized_new_prefix, new_code, normalized_old_prefix, old_code),
                )

            if not normalized_web_movie_updates:
                cursor.execute(
                    'UPDATE code_prefix_movies SET prefix = ? WHERE prefix = ?',
                    (normalized_new_prefix, normalized_old_prefix),
                )

            cursor.execute(
                'UPDATE code_prefix_enrichments SET prefix = ? WHERE prefix = ?',
                (normalized_new_prefix, normalized_old_prefix),
            )
            cursor.execute(
                'UPDATE hidden_code_prefixes SET prefix = ? WHERE prefix = ?',
                (normalized_new_prefix, normalized_old_prefix),
            )
            conn.commit()
            return len(normalized_code_updates)

    def delete_code_prefix(self, prefix):
        normalized_prefix = str(prefix or '').strip().upper()
        if not normalized_prefix:
            raise ValueError('番号前缀不能为空')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR IGNORE INTO hidden_code_prefixes (prefix) VALUES (?)',
                (normalized_prefix,),
            )
            cursor.execute('DELETE FROM code_prefix_movies WHERE prefix = ?', (normalized_prefix,))
            cursor.execute('DELETE FROM code_prefix_enrichments WHERE prefix = ?', (normalized_prefix,))
            conn.commit()
            return 1

    def get_path_by_value(self, folder_path):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, path, created_at, last_total_bytes, last_used_bytes,
                       last_free_bytes, last_usage_percent, last_volume_type, last_checked_at
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
            'last_total_bytes': row[3] or 0,
            'last_used_bytes': row[4] or 0,
            'last_free_bytes': row[5] or 0,
            'last_usage_percent': row[6] or 0,
            'last_volume_type': row[7] or '',
            'last_checked_at': row[8] or '',
        }

    def list_videos(self, search_text=''):
        search_text = (search_text or '').strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if search_text:
                like_value = f'%{search_text}%'
                cursor.execute(
                    '''
                    SELECT code, title, author, duration, size, storage_location,
                           avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors,
                           release_date, maker, publisher,
                           avfan_enrichment_status, javtxt_enrichment_status
                    FROM processed_videos
                    WHERE code LIKE ? OR title LIKE ? OR author LIKE ? OR storage_location LIKE ?
                       OR avfan_movie_id LIKE ? OR javtxt_movie_id LIKE ? OR javtxt_title LIKE ? OR javtxt_actors LIKE ?
                       OR release_date LIKE ? OR maker LIKE ? OR publisher LIKE ?
                       OR avfan_enrichment_status LIKE ? OR javtxt_enrichment_status LIKE ?
                    ORDER BY code
                    ''',
                    (
                        like_value, like_value, like_value, like_value,
                        like_value, like_value, like_value, like_value,
                        like_value, like_value, like_value,
                        like_value, like_value,
                    ),
                )
            else:
                cursor.execute(
                    '''
                    SELECT code, title, author, duration, size, storage_location,
                           avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors,
                           release_date, maker, publisher,
                           avfan_enrichment_status, javtxt_enrichment_status
                    FROM processed_videos
                    ORDER BY code
                    '''
                )

            rows = cursor.fetchall()

        return [
            {
                'code': row[0] or '',
                'title': row[1] or '',
                'author': sanitize_actor_text(row[2] or ''),
                'duration': row[3] or '',
                'size': row[4] or '',
                'storage_location': row[5] or '',
                'avfan_movie_id': row[6] or '',
                'javtxt_movie_id': row[7] or '',
                'javtxt_url': row[8] or '',
                'javtxt_title': row[9] or '',
                'javtxt_actors': sanitize_actor_text(row[10] or ''),
                'release_date': row[11] or '',
                'maker': row[12] or '',
                'publisher': row[13] or '',
                'avfan_enrichment_status': row[14] or UNENRICHED_STATUS,
                'javtxt_enrichment_status': row[15] or UNENRICHED_STATUS,
                'enrichment_status': build_video_enrichment_status_text(row[14], row[15]),
            }
            for row in rows
        ]

    def list_videos_for_enrichment(self, limit, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        status_column, _, _ = self._video_source_columns(source_key)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT code, title, author
                FROM processed_videos
                WHERE COALESCE({status_column}, ?) IN (?, ?)
                ORDER BY code
                LIMIT ?
                ''',
                (
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    FAILED_STATUS,
                    int(limit),
                ),
            )
            return [
                {
                    'code': row[0] or '',
                    'title': row[1] or '',
                    'author': row[2] or '',
                }
                for row in cursor.fetchall()
            ]

    def update_video_enrichment(self, code, info, status=ENRICHED_STATUS, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, error_column, at_column = self._video_source_columns(normalized_source)
        sanitized_author = sanitize_actor_text(info.get('author', ''))
        sanitized_javtxt_actors = sanitize_actor_text(info.get('javtxt_actors', ''))
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET javtxt_movie_id = ?,
                        javtxt_url = ?,
                        javtxt_title = ?,
                        javtxt_actors = ?,
                        title = COALESCE(NULLIF(?, ''), title),
                        author = ?,
                        release_date = COALESCE(NULLIF(?, ''), release_date),
                        maker = COALESCE(NULLIF(?, ''), maker),
                        publisher = COALESCE(NULLIF(?, ''), publisher),
                        {status_column} = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    (
                        info.get('javtxt_movie_id', ''),
                        info.get('javtxt_url', ''),
                        info.get('javtxt_title', ''),
                        sanitized_javtxt_actors,
                        info.get('title', ''),
                        sanitized_author,
                        info.get('release_date', ''),
                        join_values(info.get('maker')),
                        join_values(info.get('publisher')),
                        status,
                        info.get('error', ''),
                        code,
                    ),
                )
            else:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET avfan_movie_id = ?,
                        release_date = ?,
                        maker = ?,
                        publisher = ?,
                        {status_column} = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    (
                        info.get('avfan_movie_id', ''),
                        info.get('release_date', ''),
                        join_values(info.get('maker')),
                        join_values(info.get('publisher')),
                        status,
                        info.get('error', ''),
                        code,
                    ),
                )

            self._refresh_combined_video_status(cursor, code, info.get('error', ''))
            conn.commit()

    def mark_video_no_search_results(self, code, error='未搜索到匹配影片', source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        self._update_video_source_status(code, source_key, NO_SEARCH_RESULTS_STATUS, error)

    def mark_video_enrichment_failed(self, code, error, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        self._update_video_source_status(code, source_key, FAILED_STATUS, error)

    def _update_video_source_status(self, code, source_key, status, error):
        status_column, error_column, at_column = self._video_source_columns(source_key)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET {status_column} = ?,
                    {error_column} = ?,
                    {at_column} = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (status, error, code),
            )
            self._refresh_combined_video_status(cursor, code, error)
            conn.commit()

    def _refresh_combined_video_status(self, cursor, code, error_message=''):
        cursor.execute(
            '''
            SELECT avfan_enrichment_status, javtxt_enrichment_status
            FROM processed_videos
            WHERE code = ?
            ''',
            (code,),
        )
        row = cursor.fetchone() or (UNENRICHED_STATUS, UNENRICHED_STATUS)
        cursor.execute(
            '''
            UPDATE processed_videos
            SET enrichment_status = ?,
                enrichment_error = ?,
                enriched_at = CURRENT_TIMESTAMP
            WHERE code = ?
            ''',
            (build_video_enrichment_status_text(row[0], row[1]), error_message, code),
        )

    def count_videos_by_enrichment_status(self, status, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        status_column, _, _ = self._video_source_columns(source_key)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT COUNT(*)
                FROM processed_videos
                WHERE COALESCE({status_column}, ?) = ?
                ''',
                (UNENRICHED_STATUS, status),
            )
            return int(cursor.fetchone()[0] or 0)

    def get_video_enrichment_summary(self, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        status_column, _, _ = self._video_source_columns(source_key)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT
                    COUNT(*) AS total_count,
                    SUM(
                        CASE
                            WHEN COALESCE({status_column}, ?) = ? THEN 1
                            ELSE 0
                        END
                    ) AS enriched_count
                FROM processed_videos
                ''',
                (UNENRICHED_STATUS, ENRICHED_STATUS),
            )
            row = cursor.fetchone() or (0, 0)

        total_count = int(row[0] or 0)
        enriched_count = int(row[1] or 0)
        unenriched_count = max(total_count - enriched_count, 0)
        return {
            'enriched_count': enriched_count,
            'unenriched_count': unenriched_count,
            'total_count': total_count,
        }

    def reset_video_enrichments(self, codes):
        normalized_codes = [
            str(code or '').strip().upper()
            for code in (codes or [])
            if str(code or '').strip()
        ]
        if not normalized_codes:
            return 0

        placeholders = ','.join('?' for _ in normalized_codes)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET avfan_movie_id = '',
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_title = '',
                    javtxt_actors = '',
                    release_date = '',
                    maker = '',
                    publisher = '',
                    enrichment_status = ?,
                    enrichment_error = '',
                    enriched_at = NULL,
                    avfan_enrichment_status = ?,
                    avfan_enrichment_error = '',
                    avfan_enriched_at = NULL,
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = '',
                    javtxt_enriched_at = NULL
                WHERE code IN ({placeholders})
                ''',
                [
                    build_video_enrichment_status_text(UNENRICHED_STATUS, UNENRICHED_STATUS),
                    UNENRICHED_STATUS,
                    UNENRICHED_STATUS,
                    *normalized_codes,
                ],
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def get_video_count(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM processed_videos')
            return int(cursor.fetchone()[0] or 0)

    def get_actor_count(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM actors')
            return int(cursor.fetchone()[0] or 0)

    def get_videos_by_codes(self, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = str(code or '').strip().upper()
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)

        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT code, title, author, duration, size, storage_location
                FROM processed_videos
                WHERE code IN ({placeholders})
                ''',
                normalized_codes,
            )
            rows = cursor.fetchall()

        return {
            (row[0] or ''): {
                'code': row[0] or '',
                'title': row[1] or '',
                'author': sanitize_actor_text(row[2] or ''),
                'duration': row[3] or '',
                'size': row[4] or '',
                'storage_location': row[5] or '',
            }
            for row in rows
        }

    def get_javtxt_actor_cache_by_codes(self, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = str(code or '').strip().upper()
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)

        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT code, javtxt_actors, javtxt_movie_id, javtxt_url, javtxt_enrichment_status
                FROM processed_videos
                WHERE code IN ({placeholders})
                ''',
                normalized_codes,
            )
            rows = cursor.fetchall()

        return {
            (row[0] or ''): {
                'code': row[0] or '',
                'javtxt_actors': sanitize_actor_text(row[1] or ''),
                'javtxt_movie_id': row[2] or '',
                'javtxt_url': row[3] or '',
                'javtxt_enrichment_status': row[4] or UNENRICHED_STATUS,
            }
            for row in rows
        }

    def save_javtxt_cache_for_video(self, code, info, status=ENRICHED_STATUS, error=''):
        normalized_code = str(code or '').strip().upper()
        if not normalized_code:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE processed_videos
                SET javtxt_movie_id = COALESCE(NULLIF(?, ''), javtxt_movie_id),
                    javtxt_url = COALESCE(NULLIF(?, ''), javtxt_url),
                    javtxt_title = COALESCE(NULLIF(?, ''), javtxt_title),
                    javtxt_actors = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = ?,
                    javtxt_enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (
                    str((info or {}).get('javtxt_movie_id', '') or '').strip(),
                    str((info or {}).get('javtxt_url', '') or '').strip(),
                    str((info or {}).get('javtxt_title', '') or '').strip(),
                    sanitize_actor_text((info or {}).get('javtxt_actors', '')),
                    str(status or ENRICHED_STATUS),
                    str(error or ''),
                    normalized_code,
                ),
            )
            self._refresh_combined_video_status(cursor, normalized_code, str(error or ''))
            conn.commit()
            return int(cursor.rowcount or 0)

    def import_local_videos(self, records):
        normalized_records = {}
        for record in records or []:
            code = str((record or {}).get('code', '')).strip().upper()
            if not code:
                continue
            normalized_records[code] = {
                'code': code,
                'storage_location': str((record or {}).get('storage_location', '') or '').strip(),
                'size': str((record or {}).get('size', '') or '').strip(),
            }

        if not normalized_records:
            return 0

        codes = list(normalized_records.keys())
        existing_records = self.get_videos_by_codes(codes)
        new_records = [normalized_records[code] for code in codes if code not in existing_records]
        existing_updates = [normalized_records[code] for code in codes if code in existing_records]

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            if new_records:
                cursor.executemany(
                    '''
                    INSERT INTO processed_videos (
                        code,
                        title,
                        author,
                        duration,
                        size,
                        storage_location,
                        enrichment_status,
                        avfan_enrichment_status,
                        javtxt_enrichment_status
                    )
                    VALUES (?, '', '', '', ?, ?, ?, ?, ?)
                    ''',
                    [
                        (
                            record['code'],
                            record['size'],
                            record['storage_location'],
                            build_video_enrichment_status_text(UNENRICHED_STATUS, UNENRICHED_STATUS),
                            UNENRICHED_STATUS,
                            UNENRICHED_STATUS,
                        )
                        for record in new_records
                    ],
                )

            if existing_updates:
                cursor.executemany(
                    '''
                    UPDATE processed_videos
                    SET size = CASE WHEN ? <> '' THEN ? ELSE size END,
                        storage_location = CASE WHEN ? <> '' THEN ? ELSE storage_location END
                    WHERE code = ?
                    ''',
                    [
                        (
                            record['size'],
                            record['size'],
                            record['storage_location'],
                            record['storage_location'],
                            record['code'],
                        )
                        for record in existing_updates
                    ],
                )

            conn.commit()

        return len(new_records)

    def list_hidden_actors(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM hidden_actors')
            return {
                str(row[0] or '').strip()
                for row in cursor.fetchall()
                if str(row[0] or '').strip()
            }

    def insert_missing_actors(self, actors):
        hidden_actors = self.list_hidden_actors()
        normalized_actors = []
        seen = set()
        for actor in actors or []:
            name = str((actor or {}).get('name', '')).strip()
            if (
                not name
                or is_ignored_actor_name(name)
                or name in seen
                or name in hidden_actors
            ):
                continue
            seen.add(name)
            normalized_actors.append(
                {
                    'name': name,
                    'birthday': str((actor or {}).get('birthday', '') or '').strip(),
                    'age': str((actor or {}).get('age', '') or '').strip(),
                    'matched': 1 if bool((actor or {}).get('matched')) else 0,
                }
            )

        if not normalized_actors:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                INSERT OR IGNORE INTO actors (name, birthday, age, matched)
                VALUES (?, ?, ?, ?)
                ''',
                [
                    (
                        actor['name'],
                        actor['birthday'],
                        actor['age'],
                        actor['matched'],
                    )
                    for actor in normalized_actors
                ],
            )
            conn.commit()
            return int(cursor.rowcount or 0)

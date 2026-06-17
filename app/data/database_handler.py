import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
    is_no_result_status,
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
from app.core.video_code import standardize_video_code
from app.core.javtxt_video_state import (
    build_javtxt_library_status,
    is_javtxt_eligible_movie,
    summarize_javtxt_movies,
)
from app.core.javtxt_entry_state import (
    JAVTXT_SEARCH_STATE_FAILED,
    JAVTXT_SEARCH_STATE_NO_RESULT,
    classify_search_state,
    is_manual_category_candidate,
    is_resolved_search_state,
    is_retryable_search_state,
    normalize_actor_raw_text,
)
from app.core.ladder_board import normalize_ladder_board_key, normalize_ladder_entity_type, normalize_ladder_tier
from app.core.second_source_actor_text import is_unpublished_actor_text, normalize_second_source_actor_text
from app.core.project_paths import DATABASE_FILE
from app.services.actor_identifier import IGNORED_ACTOR_NAMES, is_ignored_actor_name


JAVTXT_INELIGIBLE_ERROR = 'JAVTXT 页面不满足补全条件'
from app.services.video_category_service import (
    MANUAL_CATEGORY_TIER_FIRST,
    MANUAL_CATEGORY_TIER_SECOND,
    MANUAL_CATEGORY_TIER_THIRD,
    VIDEO_CATEGORY_OPTIONS,
    classify_manual_category_tier,
    count_video_actors,
    detect_video_category,
    normalize_video_category,
)


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

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=60)
        conn.execute('PRAGMA busy_timeout = 60000')
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """初始化表结构（以 code 为主键实现绝对去重）"""
        with self._connect() as conn:
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
            self._ensure_column(cursor, 'processed_videos', 'javtxt_actors_raw', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_tags', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'javtxt_release_date', 'TEXT')
            self._ensure_column(cursor, 'processed_videos', 'video_category', 'TEXT')
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
                    javtxt_tags TEXT,
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
                    javtxt_tags TEXT,
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
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS manual_category_staging (
                    code TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cursor.execute(
                '''
                CREATE TABLE IF NOT EXISTS ladder_entries (
                    board_key TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_name TEXT NOT NULL,
                    tier TEXT NOT NULL DEFAULT '',
                    medal TEXT DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (board_key, entity_type, entity_name)
                )
                '''
            )
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
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_movie_id', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_url', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_tags', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'javtxt_release_date', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'author_raw', 'TEXT')
            self._ensure_column(cursor, 'code_prefix_movies', 'video_category', 'TEXT')
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
            self._ensure_column(cursor, 'actor_movies', 'javtxt_enrichment_status', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_movie_id', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_url', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_tags', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'javtxt_release_date', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'author_raw', 'TEXT')
            self._ensure_column(cursor, 'actor_movies', 'video_category', 'TEXT')
            self._ensure_column(cursor, 'ladder_entries', 'tier', 'TEXT NOT NULL DEFAULT ""')
            self._ensure_column(cursor, 'ladder_entries', 'medal', 'TEXT DEFAULT ""')
            self._ensure_column(cursor, 'ladder_entries', 'created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_column(cursor, 'ladder_entries', 'updated_at', 'TEXT DEFAULT CURRENT_TIMESTAMP')
            self._ensure_index(cursor, 'idx_processed_videos_manual_category', 'processed_videos', 'javtxt_enrichment_status, video_category, code')
            self._ensure_index(cursor, 'idx_code_prefix_movies_code', 'code_prefix_movies', 'code')
            self._ensure_index(cursor, 'idx_code_prefix_movies_category_code', 'code_prefix_movies', 'video_category, code')
            self._ensure_index(cursor, 'idx_actor_movies_code', 'actor_movies', 'code')
            self._ensure_index(cursor, 'idx_actor_movies_category_code', 'actor_movies', 'video_category, code')
            self._ensure_index(cursor, 'idx_ladder_entries_board', 'ladder_entries', 'board_key, entity_type, tier, entity_name')
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
            cursor.execute(
                '''
                UPDATE code_prefix_movies
                SET javtxt_enrichment_status = COALESCE(
                        NULLIF(javtxt_enrichment_status, ''),
                        (
                            SELECT COALESCE(NULLIF(p.javtxt_enrichment_status, ''), ?)
                            FROM processed_videos p
                            WHERE p.code = code_prefix_movies.code
                        ),
                        ?
                    ),
                    javtxt_movie_id = COALESCE(
                        NULLIF(javtxt_movie_id, ''),
                        (
                            SELECT p.javtxt_movie_id
                            FROM processed_videos p
                            WHERE p.code = code_prefix_movies.code
                        ),
                        ''
                    ),
                    javtxt_url = COALESCE(
                        NULLIF(javtxt_url, ''),
                        (
                            SELECT p.javtxt_url
                            FROM processed_videos p
                            WHERE p.code = code_prefix_movies.code
                        ),
                        ''
                    ),
                    javtxt_tags = COALESCE(
                        NULLIF(javtxt_tags, ''),
                        (
                            SELECT p.javtxt_tags
                            FROM processed_videos p
                            WHERE p.code = code_prefix_movies.code
                        ),
                        ''
                    ),
                    javtxt_release_date = COALESCE(
                        NULLIF(javtxt_release_date, ''),
                        (
                            SELECT p.javtxt_release_date
                            FROM processed_videos p
                            WHERE p.code = code_prefix_movies.code
                        ),
                        ''
                    ),
                    author_raw = COALESCE(NULLIF(author_raw, ''), NULLIF(author, ''), '')
                ''',
                (UNENRICHED_STATUS, UNENRICHED_STATUS),
            )
            cursor.execute(
                '''
                UPDATE actor_movies
                SET javtxt_enrichment_status = COALESCE(
                        NULLIF(javtxt_enrichment_status, ''),
                        (
                            SELECT COALESCE(NULLIF(p.javtxt_enrichment_status, ''), ?)
                            FROM processed_videos p
                            WHERE p.code = actor_movies.code
                        ),
                        ?
                    ),
                    javtxt_movie_id = COALESCE(
                        NULLIF(javtxt_movie_id, ''),
                        (
                            SELECT p.javtxt_movie_id
                            FROM processed_videos p
                            WHERE p.code = actor_movies.code
                        ),
                        ''
                    ),
                    javtxt_url = COALESCE(
                        NULLIF(javtxt_url, ''),
                        (
                            SELECT p.javtxt_url
                            FROM processed_videos p
                            WHERE p.code = actor_movies.code
                        ),
                        ''
                    ),
                    javtxt_tags = COALESCE(
                        NULLIF(javtxt_tags, ''),
                        (
                            SELECT p.javtxt_tags
                            FROM processed_videos p
                            WHERE p.code = actor_movies.code
                        ),
                        ''
                    ),
                    javtxt_release_date = COALESCE(
                        NULLIF(javtxt_release_date, ''),
                        (
                            SELECT p.javtxt_release_date
                            FROM processed_videos p
                            WHERE p.code = actor_movies.code
                        ),
                        ''
                    ),
                    author_raw = COALESCE(NULLIF(author_raw, ''), NULLIF(author, ''), '')
                ''',
                (UNENRICHED_STATUS, UNENRICHED_STATUS),
            )
            cursor.execute(
                '''
                UPDATE processed_videos
                SET javtxt_actors_raw = COALESCE(NULLIF(javtxt_actors_raw, ''), NULLIF(javtxt_actors, ''), '')
                '''
            )
            cursor.executemany(
                'DELETE FROM actors WHERE lower(name) = ?',
                [(name,) for name in IGNORED_ACTOR_NAMES],
            )
            self._backfill_video_categories(cursor)
            self._clear_processed_video_javtxt_state_without_detail_reference(cursor)
            self._clear_ineligible_processed_video_javtxt_state(cursor)
            self._backfill_web_movie_categories(cursor, 'code_prefix_movies')
            self._backfill_web_movie_categories(cursor, 'actor_movies')
            self._normalize_existing_web_movie_codes(cursor)
            self._propagate_existing_web_movie_javtxt_state(cursor)
            self._clear_web_movie_javtxt_state_without_detail_reference(cursor, 'code_prefix_movies')
            self._clear_web_movie_javtxt_state_without_detail_reference(cursor, 'actor_movies')
            self._clear_legacy_web_movie_javtxt_state_without_release_date(cursor, 'code_prefix_movies')
            self._clear_legacy_web_movie_javtxt_state_without_release_date(cursor, 'actor_movies')
            self._clear_ineligible_web_movie_javtxt_state(cursor, 'code_prefix_movies')
            self._clear_ineligible_web_movie_javtxt_state(cursor, 'actor_movies')
            conn.commit()

    def _ensure_column(self, cursor, table_name, column_name, column_type):
        cursor.execute(f'PRAGMA table_info({table_name})')
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name not in existing_columns:
            cursor.execute(f'ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}')

    @staticmethod
    def _ensure_index(cursor, index_name, table_name, columns_sql):
        cursor.execute(
            f'CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns_sql})'
        )

    def _video_source_columns(self, source_key):
        source_key_text = str(source_key or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key_text) if source_key_text else ''
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            return 'javtxt_enrichment_status', 'javtxt_enrichment_error', 'javtxt_enriched_at'
        return 'avfan_enrichment_status', 'avfan_enrichment_error', 'avfan_enriched_at'

    def _library_source_columns(self, source_key):
        normalized_source = normalize_video_enrichment_source(source_key)
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            return 'javtxt_enrichment_status', 'javtxt_last_error', 'javtxt_last_enriched_at'
        return 'avfan_enrichment_status', 'avfan_last_error', 'avfan_last_enriched_at'

    @staticmethod
    def _normalize_video_category_fields(tags_text, actors_text):
        return str(tags_text or '').strip(), sanitize_actor_text(actors_text)

    def _determine_auto_video_category(self, tags_text, actors_text):
        normalized_tags, normalized_actors = self._normalize_video_category_fields(tags_text, actors_text)
        return detect_video_category(normalized_tags, normalized_actors)

    def _resolve_web_movie_category(self, movie):
        explicit_category = normalize_video_category((movie or {}).get('video_category', ''))
        if explicit_category:
            return explicit_category

        processed_category = normalize_video_category((movie or {}).get('processed_video_category', ''))
        if processed_category:
            return processed_category

        return self._determine_auto_video_category(
            (movie or {}).get('javtxt_tags', ''),
            (movie or {}).get('author', ''),
        )

    @staticmethod
    def _normalize_actor_raw_text(value):
        return normalize_actor_raw_text(value)

    def _refresh_video_category(self, cursor, code, tags_text=None, actors_text=None):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return

        cursor.execute(
            '''
            SELECT javtxt_tags, javtxt_actors, video_category
            FROM processed_videos
            WHERE code = ?
            ''',
            (normalized_code,),
        )
        row = cursor.fetchone()
        if row is None:
            return

        effective_tags = row[0] if tags_text is None else tags_text
        effective_actors = row[1] if actors_text is None else actors_text
        auto_category = self._determine_auto_video_category(effective_tags, effective_actors)
        current_category = normalize_video_category(row[2])
        if auto_category and auto_category != current_category:
            cursor.execute(
                '''
                UPDATE processed_videos
                SET video_category = ?
                WHERE code = ?
                ''',
                (auto_category, normalized_code),
            )

    def _backfill_video_categories(self, cursor):
        cursor.execute(
            '''
            SELECT code, javtxt_tags, javtxt_actors, video_category
            FROM processed_videos
            '''
        )
        rows = cursor.fetchall()
        for row in rows:
            code = standardize_video_code(row[0])
            if not code:
                continue
            current_category = normalize_video_category(row[3])
            if current_category:
                continue
            auto_category = self._determine_auto_video_category(row[1], row[2])
            if not auto_category:
                continue
            cursor.execute(
                '''
                UPDATE processed_videos
                SET video_category = ?
                WHERE code = ?
                ''',
                (auto_category, code),
            )

    def _backfill_web_movie_categories(self, cursor, table_name):
        cursor.execute(
            f'''
            SELECT rowid, code, author, javtxt_tags, video_category
            FROM {table_name}
            '''
        )
        rows = cursor.fetchall()
        for rowid, code, author, javtxt_tags, current_category in rows:
            normalized_current = normalize_video_category(current_category)
            if normalized_current:
                continue

            normalized_code = standardize_video_code(code)
            processed_category = ''
            if normalized_code:
                cursor.execute(
                    '''
                    SELECT video_category
                    FROM processed_videos
                    WHERE code = ?
                    ''',
                    (normalized_code,),
                )
                processed_row = cursor.fetchone()
                if processed_row is not None:
                    processed_category = normalize_video_category(processed_row[0])

            auto_category = processed_category or self._determine_auto_video_category(javtxt_tags, author)
            if not auto_category:
                continue

            cursor.execute(
                f'''
                UPDATE {table_name}
                SET video_category = ?
                WHERE rowid = ?
                ''',
                (auto_category, rowid),
            )

    def _clear_ineligible_web_movie_javtxt_state(self, cursor, table_name):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')

        cursor.execute(
            f'''
            SELECT rowid,
                   code,
                   title,
                   release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_release_date,
                   javtxt_enrichment_status
            FROM {table_name}
            WHERE COALESCE(javtxt_enrichment_status, '') <> ?
               OR COALESCE(javtxt_movie_id, '') <> ''
               OR COALESCE(javtxt_url, '') <> ''
               OR COALESCE(javtxt_tags, '') <> ''
            ''',
            (UNENRICHED_STATUS,),
        )
        rowids_to_mark_no_result = []
        rowids_to_preserve_terminal = []
        for (
            rowid,
            code,
            title,
            release_date,
            javtxt_tags,
            video_category,
            javtxt_release_date,
            javtxt_status,
        ) in cursor.fetchall():
            if is_javtxt_eligible_movie(
                {
                    'code': code,
                    'title': title,
                    'release_date': release_date,
                    'javtxt_release_date': javtxt_release_date,
                    'javtxt_tags': javtxt_tags,
                    'video_category': video_category,
                }
            ):
                continue
            if is_no_result_status(javtxt_status):
                rowids_to_preserve_terminal.append(rowid)
            else:
                rowids_to_mark_no_result.append(rowid)

        for index in range(0, len(rowids_to_preserve_terminal), 500):
            chunk = rowids_to_preserve_terminal[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET author = '',
                    author_raw = '',
                    javtxt_movie_id = '',
                    javtxt_url = ''
                WHERE rowid IN ({placeholders})
                ''',
                (*chunk,),
            )

        for index in range(0, len(rowids_to_mark_no_result), 500):
            chunk = rowids_to_mark_no_result[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET author = '',
                    author_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = ''
                WHERE rowid IN ({placeholders})
                ''',
                (NO_SEARCH_RESULTS_STATUS, *chunk),
            )

    def _clear_web_movie_javtxt_state_without_detail_reference(self, cursor, table_name):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')

        cursor.execute(
            f'''
            SELECT rowid
            FROM {table_name}
            WHERE COALESCE(javtxt_movie_id, '') = ''
              AND COALESCE(javtxt_url, '') = ''
              AND (
                    COALESCE(author, '') <> ''
                 OR COALESCE(author_raw, '') <> ''
                 OR COALESCE(javtxt_enrichment_status, '') = ?
              )
            ''',
            (ENRICHED_STATUS,),
        )
        rowids_to_clear = [row[0] for row in cursor.fetchall() if row and row[0] is not None]
        for index in range(0, len(rowids_to_clear), 500):
            chunk = rowids_to_clear[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET author = '',
                    author_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = '',
                    javtxt_release_date = ''
                WHERE rowid IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _clear_legacy_web_movie_javtxt_state_without_release_date(self, cursor, table_name):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')

        cursor.execute(
            f'''
            SELECT rowid
            FROM {table_name}
            WHERE COALESCE(javtxt_release_date, '') = ''
              AND COALESCE(javtxt_enrichment_status, '') NOT IN (?, ?)
              AND (
                    COALESCE(javtxt_enrichment_status, '') <> ?
                 OR COALESCE(javtxt_movie_id, '') <> ''
                 OR COALESCE(javtxt_url, '') <> ''
                 OR COALESCE(javtxt_tags, '') <> ''
              )
            ''',
            (NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS, UNENRICHED_STATUS),
        )
        rowids_to_clear = [row[0] for row in cursor.fetchall() if row and row[0] is not None]
        for index in range(0, len(rowids_to_clear), 500):
            chunk = rowids_to_clear[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = ''
                WHERE rowid IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _clear_ineligible_processed_video_javtxt_state(self, cursor):
        cursor.execute(
            '''
            SELECT code,
                   COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code),
                   release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_release_date,
                   javtxt_enrichment_status
            FROM processed_videos
            WHERE COALESCE(javtxt_enrichment_status, '') <> ?
               OR COALESCE(javtxt_movie_id, '') <> ''
               OR COALESCE(javtxt_url, '') <> ''
               OR COALESCE(javtxt_tags, '') <> ''
            ''',
            (UNENRICHED_STATUS,),
        )
        codes_to_mark_no_result = []
        codes_to_preserve_terminal = []
        for (
            code,
            title,
            release_date,
            javtxt_tags,
            video_category,
            javtxt_release_date,
            javtxt_status,
        ) in cursor.fetchall():
            if is_javtxt_eligible_movie(
                {
                    'code': code,
                    'title': title,
                    'release_date': release_date,
                    'javtxt_release_date': javtxt_release_date,
                    'javtxt_tags': javtxt_tags,
                    'video_category': video_category,
                }
            ):
                continue
            normalized_code = standardize_video_code(code)
            if normalized_code:
                if is_no_result_status(javtxt_status):
                    codes_to_preserve_terminal.append(normalized_code)
                else:
                    codes_to_mark_no_result.append(normalized_code)

        for index in range(0, len(codes_to_preserve_terminal), 500):
            chunk = codes_to_preserve_terminal[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_actors = '',
                    javtxt_actors_raw = ''
                WHERE code IN ({placeholders})
                ''',
                (*chunk,),
            )

        for index in range(0, len(codes_to_mark_no_result), 500):
            chunk = codes_to_mark_no_result[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_actors = '',
                    javtxt_actors_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = CASE
                        WHEN COALESCE(javtxt_enrichment_error, '') = '' THEN ?
                        ELSE javtxt_enrichment_error
                    END
                WHERE code IN ({placeholders})
                ''',
                (NO_SEARCH_RESULTS_STATUS, JAVTXT_INELIGIBLE_ERROR, *chunk),
            )

    def _clear_processed_video_javtxt_state_without_detail_reference(self, cursor):
        cursor.execute(
            '''
            SELECT code
            FROM processed_videos
            WHERE COALESCE(javtxt_movie_id, '') = ''
              AND COALESCE(javtxt_url, '') = ''
              AND (
                    COALESCE(javtxt_actors, '') <> ''
                 OR COALESCE(javtxt_actors_raw, '') <> ''
                 OR COALESCE(javtxt_enrichment_status, '') = ?
              )
            ''',
            (ENRICHED_STATUS,),
        )
        codes_to_clear = [
            standardize_video_code((row or [''])[0])
            for row in cursor.fetchall()
            if standardize_video_code((row or [''])[0])
        ]
        if not codes_to_clear:
            return

        for index in range(0, len(codes_to_clear), 500):
            chunk = codes_to_clear[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_title = '',
                    javtxt_actors = '',
                    javtxt_actors_raw = '',
                    javtxt_tags = '',
                    javtxt_release_date = '',
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = '',
                    javtxt_enriched_at = NULL
                WHERE code IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def sanitize_ineligible_javtxt_state(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT prefix FROM code_prefix_movies
                UNION
                SELECT prefix FROM code_prefix_enrichments
                '''
            )
            prefixes = [str((row or [''])[0] or '').strip().upper() for row in cursor.fetchall()]
            cursor.execute(
                '''
                SELECT actor_name FROM actor_movies
                UNION
                SELECT actor_name FROM actor_enrichments
                '''
            )
            actor_names = [str((row or [''])[0] or '').strip() for row in cursor.fetchall()]
            cursor.execute(
                '''
                SELECT code FROM code_prefix_movies
                UNION
                SELECT code FROM actor_movies
                '''
            )
            shared_codes = [
                standardize_video_code((row or [''])[0])
                for row in cursor.fetchall()
                if standardize_video_code((row or [''])[0])
            ]
            self._clear_processed_video_javtxt_state_without_detail_reference(cursor)
            self._clear_ineligible_processed_video_javtxt_state(cursor)
            self._clear_web_movie_javtxt_state_without_detail_reference(cursor, 'code_prefix_movies')
            self._clear_web_movie_javtxt_state_without_detail_reference(cursor, 'actor_movies')
            self._clear_legacy_web_movie_javtxt_state_without_release_date(cursor, 'code_prefix_movies')
            self._clear_legacy_web_movie_javtxt_state_without_release_date(cursor, 'actor_movies')
            self._clear_ineligible_web_movie_javtxt_state(cursor, 'code_prefix_movies')
            self._clear_ineligible_web_movie_javtxt_state(cursor, 'actor_movies')
            self._propagate_processed_video_javtxt_state_for_codes(cursor, shared_codes)
            conn.commit()

        if prefixes:
            self.refresh_code_prefix_javtxt_statuses(prefixes)
        if actor_names:
            self.refresh_actor_javtxt_statuses(actor_names)

    def _clear_processed_video_javtxt_codes(self, cursor, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return

        for index in range(0, len(normalized_codes), 500):
            chunk = normalized_codes[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE processed_videos
                SET javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_title = '',
                    javtxt_actors = '',
                    javtxt_actors_raw = '',
                    javtxt_tags = '',
                    javtxt_release_date = '',
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = '',
                    javtxt_enriched_at = NULL
                WHERE code IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _clear_web_movie_javtxt_rowids(self, cursor, table_name, rowids):
        if table_name not in {'code_prefix_movies', 'actor_movies'}:
            raise ValueError(f'Unsupported web movie table: {table_name}')
        normalized_rowids = []
        seen = set()
        for rowid in rowids or []:
            try:
                normalized_rowid = int(rowid)
            except (TypeError, ValueError):
                continue
            if normalized_rowid <= 0 or normalized_rowid in seen:
                continue
            seen.add(normalized_rowid)
            normalized_rowids.append(normalized_rowid)
        if not normalized_rowids:
            return

        for index in range(0, len(normalized_rowids), 500):
            chunk = normalized_rowids[index:index + 500]
            placeholders = ','.join('?' for _ in chunk)
            cursor.execute(
                f'''
                UPDATE {table_name}
                SET author = '',
                    author_raw = '',
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = '',
                    javtxt_url = '',
                    javtxt_tags = '',
                    javtxt_release_date = ''
                WHERE rowid IN ({placeholders})
                ''',
                (UNENRICHED_STATUS, *chunk),
            )

    def _normalize_existing_web_movie_codes(self, cursor):
        self._normalize_processed_video_codes(cursor)
        self._normalize_code_prefix_movie_codes(cursor)
        self._normalize_actor_movie_codes(cursor)
        self._normalize_manual_category_staging_codes(cursor)

    def _normalize_processed_video_codes(self, cursor):
        cursor.execute('SELECT code FROM processed_videos')
        for (code,) in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code == code:
                continue
            cursor.execute('SELECT 1 FROM processed_videos WHERE code = ?', (normalized_code,))
            if cursor.fetchone():
                cursor.execute('DELETE FROM processed_videos WHERE code = ?', (code,))
            else:
                cursor.execute('UPDATE processed_videos SET code = ? WHERE code = ?', (normalized_code, code))

    def _normalize_code_prefix_movie_codes(self, cursor):
        cursor.execute('SELECT prefix, code FROM code_prefix_movies')
        for prefix, code in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            normalized_prefix = self._extract_standard_code_prefix(normalized_code)
            if not normalized_code or not normalized_prefix:
                continue
            if normalized_code == code and normalized_prefix == prefix:
                continue
            cursor.execute(
                'SELECT 1 FROM code_prefix_movies WHERE prefix = ? AND code = ?',
                (normalized_prefix, normalized_code),
            )
            if cursor.fetchone():
                cursor.execute(
                    'DELETE FROM code_prefix_movies WHERE prefix = ? AND code = ?',
                    (prefix, code),
                )
            else:
                cursor.execute(
                    '''
                    UPDATE code_prefix_movies
                    SET prefix = ?, code = ?
                    WHERE prefix = ? AND code = ?
                    ''',
                    (normalized_prefix, normalized_code, prefix, code),
                )

    def _normalize_actor_movie_codes(self, cursor):
        cursor.execute('SELECT actor_name, code FROM actor_movies')
        for actor_name, code in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code == code:
                continue
            cursor.execute(
                'SELECT 1 FROM actor_movies WHERE actor_name = ? AND code = ?',
                (actor_name, normalized_code),
            )
            if cursor.fetchone():
                cursor.execute(
                    'DELETE FROM actor_movies WHERE actor_name = ? AND code = ?',
                    (actor_name, code),
                )
            else:
                cursor.execute(
                    'UPDATE actor_movies SET code = ? WHERE actor_name = ? AND code = ?',
                    (normalized_code, actor_name, code),
                )

    def _normalize_manual_category_staging_codes(self, cursor):
        cursor.execute('SELECT code, category FROM manual_category_staging')
        for code, category in cursor.fetchall():
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code == code:
                continue
            cursor.execute('DELETE FROM manual_category_staging WHERE code = ?', (code,))
            cursor.execute(
                '''
                INSERT INTO manual_category_staging (code, category, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (normalized_code, category),
            )

    @staticmethod
    def _extract_standard_code_prefix(code):
        match = re.match(r'^([A-Z]+)', str(code or '').strip().upper())
        return match.group(1) if match else ''

    def _normalize_web_movie_javtxt_fields(self, movie, processed_record=None):
        processed_record = processed_record or {}
        tags = self._first_nonblank_text((movie or {}).get('javtxt_tags', ''), processed_record.get('javtxt_tags', ''))
        merged_status = self._first_nonblank_text(
            (movie or {}).get('javtxt_enrichment_status', ''),
            processed_record.get('javtxt_enrichment_status', ''),
        ) or UNENRICHED_STATUS
        javtxt_release_date = self._first_nonblank_text(
            (movie or {}).get('javtxt_release_date', ''),
            processed_record.get('javtxt_release_date', ''),
        )
        effective_release_date = javtxt_release_date or self._first_nonblank_text(
            (movie or {}).get('release_date', ''),
            processed_record.get('release_date', ''),
        )
        category = self._resolve_web_movie_category(
            {
                **dict(movie or {}),
                'javtxt_tags': tags,
                'processed_video_category': processed_record.get('video_category', ''),
            }
        )
        candidate = {
            **dict(movie or {}),
            'javtxt_tags': tags,
            'javtxt_release_date': javtxt_release_date,
            'release_date': effective_release_date,
            'video_category': category,
        }
        if not is_javtxt_eligible_movie(candidate):
            if is_no_result_status(merged_status):
                return merged_status, '', '', tags, javtxt_release_date, category
            return UNENRICHED_STATUS, '', '', '', javtxt_release_date, category

        return (
            merged_status,
            self._first_nonblank_text((movie or {}).get('javtxt_movie_id', ''), processed_record.get('javtxt_movie_id', '')),
            self._first_nonblank_text((movie or {}).get('javtxt_url', ''), processed_record.get('javtxt_url', '')),
            tags,
            javtxt_release_date,
            category,
        )

    @staticmethod
    def _first_nonblank_text(*values):
        for value in values:
            text = str(value or '').strip()
            if text:
                return text
        return ''

    @staticmethod
    def _has_javtxt_detail_reference(movie):
        current = dict(movie or {})
        return bool(
            str(current.get('javtxt_movie_id', '') or '').strip()
            or str(current.get('javtxt_url', '') or '').strip()
        )

    def _normalize_web_movie_actor_fields(self, movie, javtxt_movie_id='', javtxt_url=''):
        sanitized_author = sanitize_actor_text((movie or {}).get('author', ''))
        author_raw = self._normalize_actor_raw_text((movie or {}).get('author_raw', (movie or {}).get('author', '')))
        if not self._has_javtxt_detail_reference(
            {
                'javtxt_movie_id': javtxt_movie_id,
                'javtxt_url': javtxt_url,
            }
        ):
            return '', ''
        return sanitized_author, author_raw

    def _load_web_movie_javtxt_state_by_codes(self, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        rows = []
        with self._connect() as conn:
            cursor = conn.cursor()
            for table_name in ('code_prefix_movies', 'actor_movies'):
                cursor.execute(
                    f'''
                    SELECT code, title, author, release_date, javtxt_enrichment_status,
                           javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                           author_raw, video_category
                    FROM {table_name}
                    WHERE code IN ({placeholders})
                    ''',
                    normalized_codes,
                )
                rows.extend(cursor.fetchall())

        best_rows = {}
        for row in rows:
            candidate = {
                'code': row[0] or '',
                'title': row[1] or '',
                'author': sanitize_actor_text(row[2] or ''),
                'release_date': row[3] or '',
                'javtxt_enrichment_status': row[4] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[5] or '',
                'javtxt_url': row[6] or '',
                'javtxt_tags': row[7] or '',
                'javtxt_release_date': row[8] or '',
                'author_raw': self._normalize_actor_raw_text(row[9] or row[2] or ''),
                'video_category': normalize_video_category(row[10]),
            }
            normalized_code = standardize_video_code(candidate['code'])
            if not normalized_code:
                continue
            current = best_rows.get(normalized_code)
            if current is None or self._web_movie_javtxt_state_score(candidate) > self._web_movie_javtxt_state_score(current):
                best_rows[normalized_code] = candidate
        return best_rows

    @staticmethod
    def _web_movie_javtxt_state_score(record):
        current = dict(record or {})
        has_detail = 1 if (
            str(current.get('javtxt_movie_id', '') or '').strip()
            or str(current.get('javtxt_url', '') or '').strip()
        ) else 0
        search_state = classify_search_state(current, cached_row=current)
        state_score = {
            'resolved': 4,
            'no_result': 3,
            'failed': 2,
            'unsearched': 1,
        }.get(search_state, 0)
        return (
            has_detail,
            state_score,
            len(str(current.get('author', '') or '').strip()),
            len(str(current.get('javtxt_tags', '') or '').strip()),
        )

    @staticmethod
    def _merge_javtxt_state_records(primary=None, fallback=None):
        primary = dict(primary or {})
        fallback = dict(fallback or {})
        if not fallback:
            return primary
        merged = dict(primary)
        for field_name in (
            'javtxt_enrichment_status',
            'javtxt_movie_id',
            'javtxt_url',
            'javtxt_tags',
            'javtxt_release_date',
            'release_date',
            'video_category',
        ):
            if not str(merged.get(field_name, '') or '').strip() and str(fallback.get(field_name, '') or '').strip():
                merged[field_name] = fallback.get(field_name, '')
        return merged

    @staticmethod
    def _merge_web_movie_actor_source(movie=None, fallback=None):
        merged = dict(movie or {})
        fallback = dict(fallback or {})
        for field_name in ('author', 'author_raw'):
            if not str(merged.get(field_name, '') or '').strip() and str(fallback.get(field_name, '') or '').strip():
                merged[field_name] = fallback.get(field_name, '')
        return merged

    def _propagate_web_movie_javtxt_state_for_codes(self, cursor, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return 0

        placeholders = ','.join('?' for _ in normalized_codes)
        candidates = []
        for table_name in ('code_prefix_movies', 'actor_movies'):
            cursor.execute(
                f'''
                SELECT code, title, author, release_date, javtxt_enrichment_status,
                       javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date,
                       author_raw, video_category
                FROM {table_name}
                WHERE code IN ({placeholders})
                  AND (COALESCE(javtxt_movie_id, '') <> '' OR COALESCE(javtxt_url, '') <> '')
                ''',
                normalized_codes,
            )
            candidates.extend(cursor.fetchall())

        best_by_code = {}
        for row in candidates:
            candidate = {
                'code': row[0] or '',
                'title': row[1] or '',
                'author': sanitize_actor_text(row[2] or ''),
                'release_date': row[3] or '',
                'javtxt_enrichment_status': row[4] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[5] or '',
                'javtxt_url': row[6] or '',
                'javtxt_tags': row[7] or '',
                'javtxt_release_date': row[8] or '',
                'author_raw': self._normalize_actor_raw_text(row[9] or row[2] or ''),
                'video_category': normalize_video_category(row[10]),
            }
            normalized_code = standardize_video_code(candidate['code'])
            if not normalized_code:
                continue
            current = best_by_code.get(normalized_code)
            if current is None or self._web_movie_javtxt_state_score(candidate) > self._web_movie_javtxt_state_score(current):
                best_by_code[normalized_code] = candidate

        if not best_by_code:
            return 0

        updates = [
            (
                state['author'],
                state['author_raw'],
                state['javtxt_enrichment_status'],
                state['javtxt_movie_id'],
                state['javtxt_url'],
                state['javtxt_tags'],
                state['javtxt_release_date'],
                state['javtxt_release_date'] or state['release_date'],
                state['video_category'],
                code,
            )
            for code, state in best_by_code.items()
        ]
        updated_count = 0
        for table_name in ('code_prefix_movies', 'actor_movies'):
            cursor.executemany(
                f'''
                UPDATE {table_name}
                SET author = ?,
                    author_raw = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?,
                    javtxt_url = ?,
                    javtxt_tags = ?,
                    javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                    release_date = COALESCE(NULLIF(?, ''), release_date),
                    video_category = COALESCE(NULLIF(?, ''), video_category)
                WHERE code = ?
                ''',
                updates,
            )
            updated_count += int(cursor.rowcount or 0)
        return updated_count

    def _propagate_existing_web_movie_javtxt_state(self, cursor):
        cursor.execute(
            '''
            SELECT code
            FROM code_prefix_movies
            WHERE COALESCE(javtxt_movie_id, '') <> '' OR COALESCE(javtxt_url, '') <> ''
            UNION
            SELECT code
            FROM actor_movies
            WHERE COALESCE(javtxt_movie_id, '') <> '' OR COALESCE(javtxt_url, '') <> ''
            '''
        )
        codes = [
            standardize_video_code((row or [''])[0])
            for row in cursor.fetchall()
            if standardize_video_code((row or [''])[0])
        ]
        for index in range(0, len(codes), 500):
            self._propagate_web_movie_javtxt_state_for_codes(cursor, codes[index:index + 500])

    def _load_processed_video_javtxt_state_by_codes(self, cursor, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        cursor.execute(
            f'''
            SELECT code,
                   COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code),
                   release_date,
                   javtxt_release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_enrichment_status,
                   javtxt_movie_id,
                   javtxt_url,
                   javtxt_actors,
                   javtxt_actors_raw
            FROM processed_videos
            WHERE code IN ({placeholders})
            ''',
            normalized_codes,
        )
        return {
            standardize_video_code(row[0]): {
                'code': row[0] or '',
                'title': row[1] or '',
                'release_date': row[2] or '',
                'javtxt_release_date': row[3] or '',
                'javtxt_tags': row[4] or '',
                'video_category': normalize_video_category(row[5]),
                'javtxt_enrichment_status': row[6] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[7] or '',
                'javtxt_url': row[8] or '',
                'author': sanitize_actor_text(row[9] or ''),
                'author_raw': self._normalize_actor_raw_text(row[10] or row[9] or ''),
            }
            for row in cursor.fetchall()
            if standardize_video_code(row[0])
        }

    def _propagate_processed_video_javtxt_state_for_codes(self, cursor, codes):
        processed_rows = self._load_processed_video_javtxt_state_by_codes(cursor, codes)
        if not processed_rows:
            return 0

        updates = []
        for code, row in processed_rows.items():
            candidate = {
                'code': code,
                'title': row.get('title', ''),
                'release_date': row.get('release_date', ''),
                'javtxt_release_date': row.get('javtxt_release_date', ''),
                'javtxt_tags': row.get('javtxt_tags', ''),
                'video_category': row.get('video_category', ''),
            }
            if is_javtxt_eligible_movie(candidate):
                javtxt_status = str(row.get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
                javtxt_movie_id = str(row.get('javtxt_movie_id', '') or '').strip()
                javtxt_url = str(row.get('javtxt_url', '') or '').strip()
                javtxt_tags = str(row.get('javtxt_tags', '') or '').strip()
                javtxt_release_date = str(row.get('javtxt_release_date', '') or '').strip()
                release_date = str(row.get('release_date', '') or '').strip()
                video_category = normalize_video_category(row.get('video_category', ''))
                has_detail_reference = self._has_javtxt_detail_reference(
                    {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
                )
                if javtxt_status == ENRICHED_STATUS and not has_detail_reference:
                    javtxt_status = UNENRICHED_STATUS
                author = sanitize_actor_text(row.get('author', '')) if has_detail_reference else ''
                author_raw = self._normalize_actor_raw_text(row.get('author_raw', '')) if has_detail_reference else ''
            else:
                javtxt_status = str(row.get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
                if not is_no_result_status(javtxt_status):
                    javtxt_status = UNENRICHED_STATUS
                javtxt_movie_id = ''
                javtxt_url = ''
                javtxt_tags = str(row.get('javtxt_tags', '') or '').strip() if is_no_result_status(javtxt_status) else ''
                javtxt_release_date = str(row.get('javtxt_release_date', '') or '').strip()
                release_date = str(row.get('release_date', '') or '').strip()
                video_category = normalize_video_category(row.get('video_category', ''))
                author = ''
                author_raw = ''

            updates.append(
                (
                    author,
                    author_raw,
                    javtxt_status,
                    javtxt_movie_id,
                    javtxt_url,
                    javtxt_tags,
                    javtxt_release_date,
                    release_date,
                    video_category,
                    code,
                )
            )

        updated_count = 0
        for table_name in ('code_prefix_movies', 'actor_movies'):
            cursor.executemany(
                f'''
                UPDATE {table_name}
                SET author = ?,
                    author_raw = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?,
                    javtxt_url = ?,
                    javtxt_tags = ?,
                    javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                    release_date = COALESCE(NULLIF(?, ''), release_date),
                    video_category = COALESCE(NULLIF(?, ''), video_category)
                WHERE code = ?
                ''',
                updates,
            )
            updated_count += int(cursor.rowcount or 0)
        return updated_count

    def _list_web_movie_parent_keys_for_codes(self, cursor, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)
        if not normalized_codes:
            return set(), set()

        placeholders = ','.join('?' for _ in normalized_codes)
        cursor.execute(
            f'''
            SELECT DISTINCT prefix
            FROM code_prefix_movies
            WHERE code IN ({placeholders})
            ''',
            normalized_codes,
        )
        prefixes = {
            str((row or [''])[0] or '').strip().upper()
            for row in cursor.fetchall()
            if str((row or [''])[0] or '').strip()
        }
        cursor.execute(
            f'''
            SELECT DISTINCT actor_name
            FROM actor_movies
            WHERE code IN ({placeholders})
            ''',
            normalized_codes,
        )
        actor_names = {
            str((row or [''])[0] or '').strip()
            for row in cursor.fetchall()
            if str((row or [''])[0] or '').strip()
        }
        return prefixes, actor_names

    def _refresh_web_movie_parent_javtxt_statuses_for_codes(self, codes):
        normalized_codes = [
            standardize_video_code(code)
            for code in (codes or [])
            if standardize_video_code(code)
        ]
        if not normalized_codes:
            return

        with self._connect() as conn:
            cursor = conn.cursor()
            prefixes, actor_names = self._list_web_movie_parent_keys_for_codes(cursor, normalized_codes)

        if prefixes:
            self.refresh_code_prefix_javtxt_statuses(sorted(prefixes))
        if actor_names:
            self.refresh_actor_javtxt_statuses(sorted(actor_names))

    def save_plans(self, plans):
        """将扫描到的计划列表批量写入/更新到数据库"""
        if not plans:
            return 0

        success_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            for plan in plans:
                normalized_code = standardize_video_code(plan.metadata.code)
                if not normalized_code:
                    continue
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
                    normalized_code,
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
        with self._connect() as conn:
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

        with self._connect() as conn:
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
            enrichment_status = str((record or {}).get('enrichment_status', '') or row[5] or '').strip()
            if not enrichment_status:
                enrichment_status = build_library_enrichment_status_text(
                    (record or {}).get('avfan_enrichment_status', ''),
                    (record or {}).get('javtxt_enrichment_status', ''),
                )
            results.append(
                {
                    'name': actor_name,
                    'birthday': row[1] or '',
                    'age': row[2] or '',
                    'matched': bool(row[3]),
                    'actor_id': row[4] or '',
                    'enrichment_status': enrichment_status or UNENRICHED_STATUS,
                }
            )
        return results

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

    def _build_live_actor_enrichment_status(self, enrichment, movies, cache_rows=None):
        avfan_status = str((enrichment or {}).get('avfan_enrichment_status', '') or '').strip()
        if not avfan_status:
            avfan_status = str((enrichment or {}).get('enrichment_status', '') or '').strip() or UNENRICHED_STATUS

        javtxt_record_status = str((enrichment or {}).get('javtxt_enrichment_status', '')).strip() or UNENRICHED_STATUS
        if cache_rows is None:
            cache_rows = self.get_javtxt_actor_cache_by_codes(
                [standardize_video_code((movie or {}).get('code', '')) for movie in (movies or [])]
            )
        summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
        javtxt_status = javtxt_record_status if summary['total_count'] <= 0 else build_javtxt_library_status(movies, cache_rows=cache_rows)

        return build_library_enrichment_status_text(avfan_status, javtxt_status)

    @staticmethod
    def _has_javtxt_author(movie):
        return bool(normalize_second_source_actor_text((movie or {}).get('author', '')))

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
        normalized_movies = []
        if movies:
            for movie in movies:
                if not movie or not movie.get('code'):
                    continue
                normalized_code = standardize_video_code(movie.get('code', ''))
                if not normalized_code:
                    continue
                normalized_movie = dict(movie)
                normalized_movie['code'] = normalized_code
                normalized_movies.append(normalized_movie)
        processed_videos = self.get_videos_by_codes([movie['code'] for movie in normalized_movies]) if normalized_movies else {}
        web_javtxt_states = self._load_web_movie_javtxt_state_by_codes([movie['code'] for movie in normalized_movies]) if normalized_movies else {}
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM code_prefix_movies WHERE prefix = ?', (prefix,))
            if normalized_movies:
                values = []
                for movie in normalized_movies:
                    normalized_code = movie['code']
                    processed_record = self._merge_javtxt_state_records(
                        processed_videos.get(normalized_code, {}) or {},
                        web_javtxt_states.get(normalized_code, {}) or {},
                    )
                    movie_with_preserved_actor = self._merge_web_movie_actor_source(
                        movie,
                        web_javtxt_states.get(normalized_code, {}) or {},
                    )
                    (
                        javtxt_status,
                        javtxt_movie_id,
                        javtxt_url,
                        javtxt_tags,
                        javtxt_release_date,
                        video_category,
                    ) = self._normalize_web_movie_javtxt_fields(movie_with_preserved_actor, processed_record)
                    author, author_raw = self._normalize_web_movie_actor_fields(
                        movie_with_preserved_actor,
                        javtxt_movie_id=javtxt_movie_id,
                        javtxt_url=javtxt_url,
                    )
                    if javtxt_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(
                        {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
                    ):
                        javtxt_status = UNENRICHED_STATUS
                    values.append(
                        (
                            prefix,
                            normalized_code,
                            movie.get('title', ''),
                            author,
                            javtxt_release_date or movie.get('release_date', ''),
                            movie.get('avfan_url', ''),
                            int(movie.get('page_number', 1) or 1),
                            javtxt_status,
                            javtxt_movie_id,
                            javtxt_url,
                            javtxt_tags,
                            javtxt_release_date,
                            author_raw,
                            video_category,
                        )
                    )
                cursor.executemany('''
                    INSERT OR REPLACE INTO code_prefix_movies (
                        prefix, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', values)
                self._propagate_web_movie_javtxt_state_for_codes(
                    cursor,
                    [movie['code'] for movie in normalized_movies],
                )
            conn.commit()
        self.refresh_code_prefix_javtxt_statuses([prefix])

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
                SELECT prefix, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category
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
                    'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'javtxt_movie_id': row[8] or '',
                    'javtxt_url': row[9] or '',
                    'javtxt_tags': row[10] or '',
                    'javtxt_release_date': row[11] or '',
                    'author_raw': row[12] or '',
                    'video_category': normalize_video_category(row[13]),
                }
                for row in cursor.fetchall()
            ]

    def list_all_code_prefix_movies(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT prefix, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category
                FROM code_prefix_movies
                ORDER BY prefix, release_date DESC, code DESC
                '''
            )

            return [
                {
                    'prefix': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': sanitize_actor_text(row[3] or ''),
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                    'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'javtxt_movie_id': row[8] or '',
                    'javtxt_url': row[9] or '',
                    'javtxt_tags': row[10] or '',
                    'javtxt_release_date': row[11] or '',
                    'author_raw': row[12] or '',
                    'video_category': normalize_video_category(row[13]),
                }
                for row in cursor.fetchall()
            ]

    def list_code_prefix_movies_by_prefixes(self, prefixes):
        normalized_prefixes = []
        seen = set()
        for prefix in prefixes or []:
            normalized_prefix = str(prefix or '').strip().upper()
            if not normalized_prefix or normalized_prefix in seen:
                continue
            seen.add(normalized_prefix)
            normalized_prefixes.append(normalized_prefix)

        results = {prefix: [] for prefix in normalized_prefixes}
        if not normalized_prefixes:
            return results

        placeholders = ','.join('?' for _ in normalized_prefixes)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT prefix, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category
                FROM code_prefix_movies
                WHERE prefix IN ({placeholders})
                ORDER BY prefix, release_date DESC, code DESC
                ''',
                normalized_prefixes,
            )

            for row in cursor.fetchall():
                prefix = row[0] or ''
                results.setdefault(prefix, []).append(
                    {
                        'prefix': prefix,
                        'code': row[1] or '',
                        'title': row[2] or '',
                        'author': sanitize_actor_text(row[3] or ''),
                        'release_date': row[4] or '',
                        'avfan_url': row[5] or '',
                        'page_number': int(row[6] or 1),
                        'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                        'javtxt_movie_id': row[8] or '',
                        'javtxt_url': row[9] or '',
                        'javtxt_tags': row[10] or '',
                        'javtxt_release_date': row[11] or '',
                        'author_raw': row[12] or '',
                        'video_category': normalize_video_category(row[13]),
                    }
                )

        return results

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
        normalized_movies = []
        if movies:
            for movie in movies:
                if not movie or not movie.get('code'):
                    continue
                normalized_code = standardize_video_code(movie.get('code', ''))
                if not normalized_code:
                    continue
                normalized_movie = dict(movie)
                normalized_movie['code'] = normalized_code
                normalized_movies.append(normalized_movie)
        processed_videos = self.get_videos_by_codes([movie['code'] for movie in normalized_movies]) if normalized_movies else {}
        web_javtxt_states = self._load_web_movie_javtxt_state_by_codes([movie['code'] for movie in normalized_movies]) if normalized_movies else {}
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM actor_movies WHERE actor_name = ?', (normalized_name,))
            if normalized_movies:
                values = []
                for movie in normalized_movies:
                    normalized_code = movie['code']
                    processed_record = self._merge_javtxt_state_records(
                        processed_videos.get(normalized_code, {}) or {},
                        web_javtxt_states.get(normalized_code, {}) or {},
                    )
                    movie_with_preserved_actor = self._merge_web_movie_actor_source(
                        movie,
                        web_javtxt_states.get(normalized_code, {}) or {},
                    )
                    (
                        javtxt_status,
                        javtxt_movie_id,
                        javtxt_url,
                        javtxt_tags,
                        javtxt_release_date,
                        video_category,
                    ) = self._normalize_web_movie_javtxt_fields(movie_with_preserved_actor, processed_record)
                    author, author_raw = self._normalize_web_movie_actor_fields(
                        movie_with_preserved_actor,
                        javtxt_movie_id=javtxt_movie_id,
                        javtxt_url=javtxt_url,
                    )
                    if javtxt_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(
                        {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
                    ):
                        javtxt_status = UNENRICHED_STATUS
                    values.append(
                        (
                            normalized_name,
                            normalized_code,
                            movie.get('title', ''),
                            author,
                            javtxt_release_date or movie.get('release_date', ''),
                            movie.get('avfan_url', ''),
                            int(movie.get('page_number', 1) or 1),
                            javtxt_status,
                            javtxt_movie_id,
                            javtxt_url,
                            javtxt_tags,
                            javtxt_release_date,
                            author_raw,
                            video_category,
                        )
                    )
                cursor.executemany('''
                    INSERT OR REPLACE INTO actor_movies (
                        actor_name, code, title, author, release_date, avfan_url, page_number,
                        javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags, javtxt_release_date, author_raw, video_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', values)
                self._propagate_web_movie_javtxt_state_for_codes(
                    cursor,
                    [movie['code'] for movie in normalized_movies],
                )
            conn.commit()
        self.refresh_actor_javtxt_statuses([normalized_name])

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
                SELECT actor_name, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category
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
                    'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'javtxt_movie_id': row[8] or '',
                    'javtxt_url': row[9] or '',
                    'javtxt_tags': row[10] or '',
                    'javtxt_release_date': row[11] or '',
                    'author_raw': row[12] or '',
                    'video_category': normalize_video_category(row[13]),
                }
                for row in cursor.fetchall()
            ]

    def list_all_actor_movies(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                SELECT actor_name, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category
                FROM actor_movies
                ORDER BY actor_name, release_date DESC, code DESC
                '''
            )

            return [
                {
                    'actor_name': row[0] or '',
                    'code': row[1] or '',
                    'title': row[2] or '',
                    'author': sanitize_actor_text(row[3] or ''),
                    'release_date': row[4] or '',
                    'avfan_url': row[5] or '',
                    'page_number': int(row[6] or 1),
                    'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                    'javtxt_movie_id': row[8] or '',
                    'javtxt_url': row[9] or '',
                    'javtxt_tags': row[10] or '',
                    'javtxt_release_date': row[11] or '',
                    'author_raw': row[12] or '',
                    'video_category': normalize_video_category(row[13]),
                }
                for row in cursor.fetchall()
            ]

    def list_actor_movies_by_names(self, actor_names):
        normalized_names = []
        seen = set()
        for actor_name in actor_names or []:
            normalized_name = str(actor_name or '').strip()
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            normalized_names.append(normalized_name)

        results = {actor_name: [] for actor_name in normalized_names}
        if not normalized_names:
            return results

        placeholders = ','.join('?' for _ in normalized_names)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT actor_name, code, title, author, release_date, avfan_url, page_number,
                       javtxt_enrichment_status, javtxt_movie_id, javtxt_url, javtxt_tags,
                       javtxt_release_date, author_raw, video_category
                FROM actor_movies
                WHERE actor_name IN ({placeholders})
                ORDER BY actor_name, release_date DESC, code DESC
                ''',
                normalized_names,
            )

            for row in cursor.fetchall():
                actor_name = row[0] or ''
                results.setdefault(actor_name, []).append(
                    {
                        'actor_name': actor_name,
                        'code': row[1] or '',
                        'title': row[2] or '',
                        'author': sanitize_actor_text(row[3] or ''),
                        'release_date': row[4] or '',
                        'avfan_url': row[5] or '',
                        'page_number': int(row[6] or 1),
                        'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                        'javtxt_movie_id': row[8] or '',
                        'javtxt_url': row[9] or '',
                        'javtxt_tags': row[10] or '',
                        'javtxt_release_date': row[11] or '',
                        'author_raw': row[12] or '',
                        'video_category': normalize_video_category(row[13]),
                    }
                )

        return results

    def reset_video_enrichments(self, codes):
        normalized_codes = [
            standardize_video_code(code)
            for code in (codes or [])
            if standardize_video_code(code)
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

    def reset_actor_enrichments(self, actor_names, source_key=None):
        normalized_names = [
            str(actor_name or '').strip()
            for actor_name in (actor_names or [])
            if str(actor_name or '').strip()
        ]
        if not normalized_names:
            return 0

        normalized_source = normalize_video_enrichment_source(source_key)
        placeholders = ','.join('?' for _ in normalized_names)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                status_column, error_column, at_column = self._library_source_columns(normalized_source)
                cursor.execute(
                    f'''
                    UPDATE actor_movies
                    SET author = '',
                        author_raw = '',
                        javtxt_enrichment_status = ?,
                        javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_tags = '',
                        video_category = ''
                    WHERE actor_name IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_names],
                )
                cursor.execute(
                    f'''
                    UPDATE actor_enrichments
                    SET {status_column} = ?,
                        javtxt_total_videos = 0,
                        {error_column} = '',
                        {at_column} = NULL
                    WHERE actor_name IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_names],
                )
                for actor_name in normalized_names:
                    self._refresh_actor_combined_status(cursor, actor_name)
            else:
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
                code = standardize_video_code(update.get('code', ''))
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

    def reset_code_prefix_enrichments(self, prefixes, source_key=None):
        normalized_prefixes = [
            str(prefix or '').strip().upper()
            for prefix in (prefixes or [])
            if str(prefix or '').strip()
        ]
        if not normalized_prefixes:
            return 0

        source_key_text = str(source_key or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key_text) if source_key_text else ''
        placeholders = ','.join('?' for _ in normalized_prefixes)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                status_column, error_column, at_column = self._library_source_columns(normalized_source)
                cursor.execute(
                    f'''
                    UPDATE code_prefix_movies
                    SET author = '',
                        author_raw = '',
                        javtxt_enrichment_status = ?,
                        javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_tags = '',
                        video_category = ''
                    WHERE prefix IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_prefixes],
                )
                cursor.execute(
                    f'''
                    UPDATE code_prefix_enrichments
                    SET {status_column} = ?,
                        javtxt_total_videos = 0,
                        {error_column} = '',
                        {at_column} = NULL
                    WHERE prefix IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_prefixes],
                )
                for prefix in normalized_prefixes:
                    self._refresh_code_prefix_combined_status(cursor, prefix)
            else:
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
                standardize_video_code(old_code),
                standardize_video_code(new_code),
            )
            for old_code, new_code in (code_updates or [])
            if standardize_video_code(old_code) and standardize_video_code(new_code)
        ]
        normalized_web_movie_updates = [
            (
                standardize_video_code(old_code),
                standardize_video_code(new_code),
            )
            for old_code, new_code in (web_movie_updates or [])
            if standardize_video_code(old_code) and standardize_video_code(new_code)
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

        with self._connect() as conn:
            cursor = conn.cursor()
            if search_text:
                like_value = f'%{search_text}%'
                cursor.execute(
                    '''
                    SELECT code, title, author, duration, size, storage_location,
                           avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors, javtxt_tags,
                           video_category,
                           release_date, maker, publisher,
                           avfan_enrichment_status, javtxt_enrichment_status
                    FROM processed_videos
                    WHERE code LIKE ? OR title LIKE ? OR author LIKE ? OR storage_location LIKE ?
                       OR avfan_movie_id LIKE ? OR javtxt_movie_id LIKE ? OR javtxt_title LIKE ? OR javtxt_actors LIKE ?
                       OR video_category LIKE ?
                       OR release_date LIKE ? OR maker LIKE ? OR publisher LIKE ?
                       OR avfan_enrichment_status LIKE ? OR javtxt_enrichment_status LIKE ?
                    ORDER BY code
                    ''',
                    (
                        like_value, like_value, like_value, like_value,
                        like_value, like_value, like_value, like_value,
                        like_value, like_value, like_value,
                        like_value,
                        like_value, like_value,
                    ),
                )
            else:
                cursor.execute(
                    '''
                    SELECT code, title, author, duration, size, storage_location,
                           avfan_movie_id, javtxt_movie_id, javtxt_url, javtxt_title, javtxt_actors, javtxt_tags,
                           video_category,
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
                'javtxt_tags': row[11] or '',
                'video_category': normalize_video_category(row[12]),
                'release_date': row[13] or '',
                'maker': row[14] or '',
                'publisher': row[15] or '',
                'avfan_enrichment_status': row[16] or UNENRICHED_STATUS,
                'javtxt_enrichment_status': row[17] or UNENRICHED_STATUS,
                'enrichment_status': build_video_enrichment_status_text(row[16], row[17]),
            }
            for row in rows
        ]

    def list_videos_for_enrichment(self, limit, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE, candidate_filter=None):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, _, _ = self._video_source_columns(normalized_source)
        candidate_filter = candidate_filter if callable(candidate_filter) else None
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                pending_rows = []
                for record in self._list_processed_video_javtxt_records(cursor):
                    if not is_javtxt_eligible_movie(record):
                        continue
                    search_state = classify_search_state(record, cached_row=record)
                    if not is_retryable_search_state(search_state):
                        continue
                    candidate = {
                        'code': record['code'],
                        'title': record['title'],
                        'author': record['local_author'] or record['author'],
                    }
                    if candidate_filter is not None and not candidate_filter(candidate):
                        continue
                    pending_rows.append(candidate)
                    if len(pending_rows) >= int(limit):
                        break
                return pending_rows
            else:
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

    def _list_processed_video_javtxt_records(self, cursor):
        cursor.execute(
            '''
            SELECT code,
                   COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code) AS display_title,
                   author,
                   javtxt_actors,
                   javtxt_actors_raw,
                   javtxt_movie_id,
                   javtxt_url,
                   javtxt_enrichment_status,
                   release_date,
                   video_category,
                   javtxt_tags,
                   javtxt_release_date
            FROM processed_videos
            ORDER BY code
            '''
        )
        return [
            {
                'code': str(row[0] or '').strip().upper(),
                'title': row[1] or '',
                'author': sanitize_actor_text(row[3] or ''),
                'author_raw': self._normalize_actor_raw_text(row[4] or row[3] or ''),
                'local_author': sanitize_actor_text(row[2] or ''),
                'javtxt_movie_id': row[5] or '',
                'javtxt_url': row[6] or '',
                'javtxt_enrichment_status': row[7] or UNENRICHED_STATUS,
                'release_date': row[8] or '',
                'video_category': normalize_video_category(row[9]),
                'javtxt_tags': row[10] or '',
                'javtxt_release_date': row[11] or '',
            }
            for row in cursor.fetchall()
            if str(row[0] or '').strip()
        ]

    def _normalize_processed_video_javtxt_payload(self, info, status):
        payload = dict(info or {})
        normalized_status = str(status or ENRICHED_STATUS).strip() or ENRICHED_STATUS
        javtxt_movie_id = str(payload.get('javtxt_movie_id', '') or '').strip()
        javtxt_url = str(payload.get('javtxt_url', '') or '').strip()
        sanitized_author = sanitize_actor_text(payload.get('author', ''))
        sanitized_javtxt_actors = sanitize_actor_text(payload.get('javtxt_actors', ''))
        raw_javtxt_actors = self._normalize_actor_raw_text(
            payload.get('javtxt_actors_raw', payload.get('author_raw', payload.get('javtxt_actors', payload.get('author', ''))))
        )
        if normalized_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(payload):
            normalized_status = UNENRICHED_STATUS
            sanitized_author = ''
            sanitized_javtxt_actors = ''
            raw_javtxt_actors = ''
        return {
            'status': normalized_status,
            'javtxt_movie_id': javtxt_movie_id,
            'javtxt_url': javtxt_url,
            'sanitized_author': sanitized_author,
            'sanitized_javtxt_actors': sanitized_javtxt_actors,
            'raw_javtxt_actors': raw_javtxt_actors,
            'sanitized_javtxt_tags': str(payload.get('javtxt_tags', '') or '').strip(),
            'title': str(payload.get('title', '') or '').strip(),
            'javtxt_title': str(payload.get('javtxt_title', '') or '').strip(),
            'release_date': str(payload.get('release_date', '') or '').strip(),
            'maker': join_values(payload.get('maker')),
            'publisher': join_values(payload.get('publisher')),
            'error': str(payload.get('error', '') or '').strip(),
        }

    def update_video_enrichment(self, code, info, status=ENRICHED_STATUS, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        source_key_text = str(source_key or '').strip()
        normalized_source = normalize_video_enrichment_source(source_key_text) if source_key_text else ''
        status_column, error_column, at_column = self._video_source_columns(normalized_source)
        normalized_javtxt = self._normalize_processed_video_javtxt_payload(info, status)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                if not self._is_processed_video_javtxt_eligible(cursor, code, info):
                    self._update_processed_video_javtxt_metadata(cursor, code, info)
                    self._refresh_video_category(
                        cursor,
                        code,
                        tags_text=normalized_javtxt['sanitized_javtxt_tags'],
                        actors_text=normalized_javtxt['sanitized_javtxt_actors'] or normalized_javtxt['sanitized_author'],
                    )
                    self._mark_processed_video_javtxt_ineligible(
                        cursor,
                        code,
                        normalized_javtxt['status'],
                        normalized_javtxt['error'],
                    )
                    self._refresh_combined_video_status(
                        cursor,
                        code,
                        normalized_javtxt['error'] or JAVTXT_INELIGIBLE_ERROR,
                    )
                    self._propagate_processed_video_javtxt_state_for_codes(cursor, [code])
                    conn.commit()
                    self._refresh_web_movie_parent_javtxt_statuses_for_codes([code])
                    return
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET javtxt_movie_id = ?,
                        javtxt_url = ?,
                        javtxt_title = ?,
                        javtxt_actors = ?,
                        javtxt_actors_raw = ?,
                        javtxt_tags = ?,
                        title = COALESCE(NULLIF(?, ''), title),
                        author = ?,
                        release_date = COALESCE(NULLIF(?, ''), release_date),
                        javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                        maker = COALESCE(NULLIF(?, ''), maker),
                        publisher = COALESCE(NULLIF(?, ''), publisher),
                        {status_column} = ?,
                        {error_column} = ?,
                        {at_column} = CURRENT_TIMESTAMP
                    WHERE code = ?
                    ''',
                    (
                        normalized_javtxt['javtxt_movie_id'],
                        normalized_javtxt['javtxt_url'],
                        normalized_javtxt['javtxt_title'],
                        normalized_javtxt['sanitized_javtxt_actors'],
                        normalized_javtxt['raw_javtxt_actors'],
                        normalized_javtxt['sanitized_javtxt_tags'],
                        normalized_javtxt['title'],
                        normalized_javtxt['sanitized_author'],
                        normalized_javtxt['release_date'],
                        normalized_javtxt['release_date'],
                        normalized_javtxt['maker'],
                        normalized_javtxt['publisher'],
                        normalized_javtxt['status'],
                        normalized_javtxt['error'],
                        code,
                    ),
                )
                self._refresh_video_category(
                    cursor,
                    code,
                    tags_text=normalized_javtxt['sanitized_javtxt_tags'],
                    actors_text=normalized_javtxt['sanitized_javtxt_actors'] or normalized_javtxt['sanitized_author'],
                )
                self._propagate_processed_video_javtxt_state_for_codes(cursor, [code])
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

            self._refresh_combined_video_status(cursor, code, normalized_javtxt['error'] if normalized_source == JAVTXT_VIDEO_SOURCE else info.get('error', ''))
            conn.commit()
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            self._refresh_web_movie_parent_javtxt_statuses_for_codes([code])

    def mark_video_no_search_results(
        self,
        code,
        error='未搜索到匹配影片',
        source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE,
        status=NO_SEARCH_RESULTS_STATUS,
    ):
        self._update_video_source_status(code, source_key, status, error)

    def mark_video_enrichment_failed(self, code, error, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        self._update_video_source_status(code, source_key, FAILED_STATUS, error)

    def _update_video_source_status(self, code, source_key, status, error):
        status_column, error_column, at_column = self._video_source_columns(source_key)
        normalized_source = normalize_video_enrichment_source(source_key)
        with self._connect() as conn:
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
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                self._propagate_processed_video_javtxt_state_for_codes(cursor, [code])
            conn.commit()
        if normalized_source == JAVTXT_VIDEO_SOURCE:
            self._refresh_web_movie_parent_javtxt_statuses_for_codes([code])

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

    def count_pending_video_enrichments(self, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE, candidate_filter=None):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, _, _ = self._video_source_columns(normalized_source)
        candidate_filter = candidate_filter if callable(candidate_filter) else None
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                pending_count = 0
                for record in self._list_processed_video_javtxt_records(cursor):
                    if not is_javtxt_eligible_movie(record):
                        continue
                    search_state = classify_search_state(record, cached_row=record)
                    if is_retryable_search_state(search_state):
                        candidate = {
                            'code': record['code'],
                            'title': record['title'],
                            'author': record['local_author'] or record['author'],
                        }
                        if candidate_filter is not None and not candidate_filter(candidate):
                            continue
                        pending_count += 1
                return pending_count
            else:
                cursor.execute(
                    f'''
                    SELECT COUNT(*)
                    FROM processed_videos
                    WHERE COALESCE({status_column}, ?) IN (?, ?)
                    ''',
                    (
                        UNENRICHED_STATUS,
                        UNENRICHED_STATUS,
                        FAILED_STATUS,
                    ),
                )
            return int(cursor.fetchone()[0] or 0)

    def get_video_enrichment_summary(self, source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE):
        normalized_source = normalize_video_enrichment_source(source_key)
        status_column, _, _ = self._video_source_columns(normalized_source)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                total_count = 0
                enriched_count = 0
                completed_count = 0
                success_count = 0
                pending_count = 0
                failed_count = 0
                no_search_count = 0
                no_detail_count = 0

                for record in self._list_processed_video_javtxt_records(cursor):
                    if not is_javtxt_eligible_movie(record):
                        continue
                    total_count += 1
                    search_state = classify_search_state(record, cached_row=record)
                    if search_state == JAVTXT_SEARCH_STATE_NO_RESULT:
                        enriched_count += 1
                        completed_count += 1
                        if str(record.get('javtxt_enrichment_status', '') or '').strip() == NO_VIDEO_DETAIL_STATUS:
                            no_detail_count += 1
                        else:
                            no_search_count += 1
                    elif is_resolved_search_state(search_state):
                        enriched_count += 1
                        completed_count += 1
                        success_count += 1
                    elif search_state == JAVTXT_SEARCH_STATE_FAILED:
                        failed_count += 1
                    else:
                        pending_count += 1

                return {
                    'enriched_count': enriched_count,
                    'completed_count': completed_count,
                    'success_count': success_count,
                    'unenriched_count': pending_count,
                    'pending_count': pending_count,
                    'failed_count': failed_count,
                    'no_search_count': no_search_count,
                    'no_detail_count': no_detail_count,
                    'total_count': total_count,
                }
            else:
                cursor.execute(
                    f'''
                    SELECT
                        COUNT(*) AS total_count,
                        SUM(
                            CASE
                                WHEN COALESCE({status_column}, ?) = ? THEN 1
                                ELSE 0
                            END
                        ) AS success_count,
                        SUM(
                            CASE
                                WHEN COALESCE({status_column}, ?) = ? THEN 1
                                ELSE 0
                            END
                        ) AS failed_count,
                        SUM(
                            CASE
                                WHEN COALESCE({status_column}, ?) = ? THEN 1
                                ELSE 0
                            END
                        ) AS no_search_count,
                        SUM(
                            CASE
                                WHEN COALESCE({status_column}, ?) = ? THEN 1
                                ELSE 0
                            END
                        ) AS no_detail_count
                    FROM processed_videos
                    ''',
                    (
                        UNENRICHED_STATUS, ENRICHED_STATUS,
                        UNENRICHED_STATUS, FAILED_STATUS,
                        UNENRICHED_STATUS, NO_SEARCH_RESULTS_STATUS,
                        UNENRICHED_STATUS, NO_VIDEO_DETAIL_STATUS,
                    ),
                )
            row = cursor.fetchone() or (0, 0, 0, 0, 0)

        total_count = int(row[0] or 0)
        success_count = int(row[1] or 0)
        failed_count = int(row[2] or 0)
        no_search_count = int(row[3] or 0)
        no_detail_count = int(row[4] or 0)
        enriched_count = success_count + no_search_count + no_detail_count
        unenriched_count = max(total_count - enriched_count - failed_count, 0)
        return {
            'enriched_count': enriched_count,
            'completed_count': enriched_count,
            'success_count': success_count,
            'unenriched_count': unenriched_count,
            'pending_count': unenriched_count,
            'failed_count': failed_count,
            'no_search_count': no_search_count,
            'no_detail_count': no_detail_count,
            'total_count': total_count,
        }

    def reset_video_enrichments(self, codes, source_key=None):
        normalized_codes = [
            standardize_video_code(code)
            for code in (codes or [])
            if standardize_video_code(code)
        ]
        if not normalized_codes:
            return 0

        normalized_source = normalize_video_enrichment_source(source_key)
        placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            cursor = conn.cursor()
            if normalized_source == JAVTXT_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_title = '',
                        javtxt_actors = '',
                        javtxt_tags = '',
                        video_category = '',
                        javtxt_enrichment_status = ?,
                        javtxt_enrichment_error = '',
                        javtxt_enriched_at = NULL
                    WHERE code IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_codes],
                )
                self._propagate_processed_video_javtxt_state_for_codes(cursor, normalized_codes)
            elif normalized_source == AVFAN_VIDEO_SOURCE:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET avfan_movie_id = '',
                        avfan_enrichment_status = ?,
                        avfan_enrichment_error = '',
                        avfan_enriched_at = NULL
                    WHERE code IN ({placeholders})
                    ''',
                    [UNENRICHED_STATUS, *normalized_codes],
                )
            else:
                cursor.execute(
                    f'''
                    UPDATE processed_videos
                    SET avfan_movie_id = '',
                        javtxt_movie_id = '',
                        javtxt_url = '',
                        javtxt_title = '',
                        javtxt_actors = '',
                        javtxt_tags = '',
                        video_category = '',
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
                self._propagate_processed_video_javtxt_state_for_codes(cursor, normalized_codes)
            for code in normalized_codes:
                self._refresh_combined_video_status(cursor, code, '')
            conn.commit()
            return int(cursor.rowcount or 0)

    def get_video_count(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM processed_videos')
            return int(cursor.fetchone()[0] or 0)

    def get_actor_count(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM actors')
            return int(cursor.fetchone()[0] or 0)

    def get_videos_by_codes(self, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)

        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT code, title, author, duration, size, storage_location, release_date, video_category,
                       javtxt_tags, javtxt_release_date, javtxt_enrichment_status, javtxt_movie_id, javtxt_url
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
                'release_date': row[6] or '',
                'video_category': normalize_video_category(row[7]),
                'javtxt_tags': row[8] or '',
                'javtxt_release_date': row[9] or '',
                'javtxt_enrichment_status': row[10] or UNENRICHED_STATUS,
                'javtxt_movie_id': row[11] or '',
                'javtxt_url': row[12] or '',
            }
            for row in rows
        }

    def bulk_update_code_prefix_movies(self, updates):
        normalized_updates = []
        for row in updates or []:
            prefix = str((row or {}).get('prefix', '') or '').strip().upper()
            code = standardize_video_code((row or {}).get('code', ''))
            if not prefix or not code:
                continue
            javtxt_status = str((row or {}).get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            javtxt_movie_id = str((row or {}).get('javtxt_movie_id', '') or '').strip()
            javtxt_url = str((row or {}).get('javtxt_url', '') or '').strip()
            author, author_raw = self._normalize_web_movie_actor_fields(
                row,
                javtxt_movie_id=javtxt_movie_id,
                javtxt_url=javtxt_url,
            )
            if javtxt_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(
                {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
            ):
                javtxt_status = UNENRICHED_STATUS
            normalized_updates.append(
                (
                    str((row or {}).get('title', '') or '').strip(),
                    author,
                    str((row or {}).get('release_date', '') or '').strip(),
                    str((row or {}).get('avfan_url', '') or '').strip(),
                    javtxt_status,
                    javtxt_movie_id,
                    javtxt_url,
                    str((row or {}).get('javtxt_tags', '') or '').strip(),
                    str((row or {}).get('javtxt_release_date', '') or '').strip(),
                    author_raw,
                    normalize_video_category((row or {}).get('video_category', '')),
                    prefix,
                    code,
                )
            )

        if not normalized_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                UPDATE code_prefix_movies
                SET title = ?,
                    author = ?,
                    release_date = ?,
                    avfan_url = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?,
                    javtxt_url = ?,
                    javtxt_tags = ?,
                    javtxt_release_date = ?,
                    author_raw = ?,
                    video_category = ?
                WHERE prefix = ? AND code = ?
                ''',
                normalized_updates,
            )
            conn.commit()
        self.refresh_code_prefix_javtxt_statuses(sorted({row[-2] for row in normalized_updates}))
        return len(normalized_updates)

    def bulk_update_actor_movies(self, updates):
        normalized_updates = []
        for row in updates or []:
            actor_name = str((row or {}).get('actor_name', '') or '').strip()
            code = standardize_video_code((row or {}).get('code', ''))
            if not actor_name or not code:
                continue
            javtxt_status = str((row or {}).get('javtxt_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
            javtxt_movie_id = str((row or {}).get('javtxt_movie_id', '') or '').strip()
            javtxt_url = str((row or {}).get('javtxt_url', '') or '').strip()
            author, author_raw = self._normalize_web_movie_actor_fields(
                row,
                javtxt_movie_id=javtxt_movie_id,
                javtxt_url=javtxt_url,
            )
            if javtxt_status == ENRICHED_STATUS and not self._has_javtxt_detail_reference(
                {'javtxt_movie_id': javtxt_movie_id, 'javtxt_url': javtxt_url}
            ):
                javtxt_status = UNENRICHED_STATUS
            normalized_updates.append(
                (
                    str((row or {}).get('title', '') or '').strip(),
                    author,
                    str((row or {}).get('release_date', '') or '').strip(),
                    str((row or {}).get('avfan_url', '') or '').strip(),
                    javtxt_status,
                    javtxt_movie_id,
                    javtxt_url,
                    str((row or {}).get('javtxt_tags', '') or '').strip(),
                    str((row or {}).get('javtxt_release_date', '') or '').strip(),
                    author_raw,
                    normalize_video_category((row or {}).get('video_category', '')),
                    actor_name,
                    code,
                )
            )

        if not normalized_updates:
            return 0

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                UPDATE actor_movies
                SET title = ?,
                    author = ?,
                    release_date = ?,
                    avfan_url = ?,
                    javtxt_enrichment_status = ?,
                    javtxt_movie_id = ?,
                    javtxt_url = ?,
                    javtxt_tags = ?,
                    javtxt_release_date = ?,
                    author_raw = ?,
                    video_category = ?
                WHERE actor_name = ? AND code = ?
                ''',
                normalized_updates,
            )
            conn.commit()
        self.refresh_actor_javtxt_statuses(sorted({row[-2] for row in normalized_updates}))
        return len(normalized_updates)

    def refresh_code_prefix_javtxt_statuses(self, prefixes):
        normalized_prefixes = []
        seen = set()
        for prefix in prefixes or []:
            normalized_prefix = str(prefix or '').strip().upper()
            if not normalized_prefix or normalized_prefix in seen:
                continue
            seen.add(normalized_prefix)
            normalized_prefixes.append(normalized_prefix)

        if not normalized_prefixes:
            return 0

        movies_by_prefix = self.list_code_prefix_movies_by_prefixes(normalized_prefixes)
        all_codes = [
            standardize_video_code((movie or {}).get('code', ''))
            for rows in movies_by_prefix.values()
            for movie in rows
            if (movie or {}).get('code')
        ]
        cache_rows = self.get_javtxt_actor_cache_by_codes(all_codes)

        with self._connect() as conn:
            cursor = conn.cursor()
            for prefix in normalized_prefixes:
                cursor.execute(
                    '''
                    INSERT OR IGNORE INTO code_prefix_enrichments (prefix)
                    VALUES (?)
                    ''',
                    (prefix,),
                )
                cursor.execute(
                    '''
                    SELECT javtxt_last_error
                    FROM code_prefix_enrichments
                    WHERE prefix = ?
                    ''',
                    (prefix,),
                )
                existing_error = str((cursor.fetchone() or [''])[0] or '')
                movies = movies_by_prefix.get(prefix, [])
                summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
                status = build_javtxt_library_status(movies, cache_rows=cache_rows)
                cursor.execute(
                    '''
                    UPDATE code_prefix_enrichments
                    SET javtxt_enrichment_status = ?,
                        javtxt_total_videos = ?,
                        javtxt_last_error = ?,
                        javtxt_last_enriched_at = CURRENT_TIMESTAMP
                    WHERE prefix = ?
                    ''',
                    (
                        status,
                        int(summary.get('total_count', 0) or 0),
                        existing_error if status == FAILED_STATUS else '',
                        prefix,
                    ),
                )
                self._refresh_code_prefix_combined_status(cursor, prefix)
            conn.commit()
        return len(normalized_prefixes)

    def refresh_actor_javtxt_statuses(self, actor_names):
        normalized_actor_names = []
        seen = set()
        for actor_name in actor_names or []:
            normalized_name = str(actor_name or '').strip()
            if not normalized_name or normalized_name in seen:
                continue
            seen.add(normalized_name)
            normalized_actor_names.append(normalized_name)

        if not normalized_actor_names:
            return 0

        movies_by_name = self.list_actor_movies_by_names(normalized_actor_names)
        all_codes = [
            standardize_video_code((movie or {}).get('code', ''))
            for rows in movies_by_name.values()
            for movie in rows
            if (movie or {}).get('code')
        ]
        cache_rows = self.get_javtxt_actor_cache_by_codes(all_codes)

        with self._connect() as conn:
            cursor = conn.cursor()
            for actor_name in normalized_actor_names:
                cursor.execute(
                    '''
                    INSERT OR IGNORE INTO actor_enrichments (actor_name)
                    VALUES (?)
                    ''',
                    (actor_name,),
                )
                cursor.execute(
                    '''
                    SELECT javtxt_last_error
                    FROM actor_enrichments
                    WHERE actor_name = ?
                    ''',
                    (actor_name,),
                )
                existing_error = str((cursor.fetchone() or [''])[0] or '')
                movies = movies_by_name.get(actor_name, [])
                summary = summarize_javtxt_movies(movies, cache_rows=cache_rows)
                status = build_javtxt_library_status(movies, cache_rows=cache_rows)
                cursor.execute(
                    '''
                    UPDATE actor_enrichments
                    SET javtxt_enrichment_status = ?,
                        javtxt_total_videos = ?,
                        javtxt_last_error = ?,
                        javtxt_last_enriched_at = CURRENT_TIMESTAMP
                    WHERE actor_name = ?
                    ''',
                    (
                        status,
                        int(summary.get('total_count', 0) or 0),
                        existing_error if status == FAILED_STATUS else '',
                        actor_name,
                    ),
                )
                self._refresh_actor_combined_status(cursor, actor_name)
            conn.commit()
        return len(normalized_actor_names)

    def list_videos_requiring_manual_category(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            staged_rows = self._list_staged_video_categories(cursor)
            staged_codes = set(staged_rows)
            manual_rows = {}
            processed_codes_to_clear = []
            prefix_rowids_to_clear = []
            actor_rowids_to_clear = []

            cursor.execute(
                '''
                SELECT code,
                       COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code) AS display_title,
                       javtxt_url,
                       javtxt_actors,
                       javtxt_actors_raw,
                       release_date,
                       javtxt_tags,
                       video_category
                FROM processed_videos
                WHERE COALESCE(javtxt_enrichment_status, ?) = ?
                  AND COALESCE(video_category, '') = ''
                ORDER BY code
                ''',
                (UNENRICHED_STATUS, ENRICHED_STATUS),
            )
            for row in cursor.fetchall():
                code = str(row[0] or '').strip().upper()
                if not code or code in staged_codes:
                    continue
                if not is_javtxt_eligible_movie(
                    {
                        'code': code,
                        'title': row[1] or '',
                        'release_date': row[5] or '',
                        'javtxt_tags': row[6] or '',
                        'video_category': normalize_video_category(row[7]),
                    }
                ):
                    if (row[2] or '').strip() or (row[3] or '').strip() or (row[4] or '').strip():
                        processed_codes_to_clear.append(code)
                    continue
                manual_rows[code] = {
                        'code': code,
                        'title': row[1] or '',
                        'avfan_url': '',
                        'javtxt_url': row[2] or '',
                        'javtxt_tags': row[6] or '',
                        'javtxt_enrichment_status': ENRICHED_STATUS,
                        'manual_tier': self._classify_manual_category_tier(row[3], row[4]),
                        'actor_count': count_video_actors(row[3]),
                    }
                if not manual_rows[code]['manual_tier']:
                    manual_rows.pop(code, None)

            cursor.execute(
                '''
                SELECT rowid,
                       code,
                       COALESCE(NULLIF(title, ''), code) AS display_title,
                       avfan_url,
                       javtxt_url,
                       author,
                       author_raw,
                       release_date,
                       javtxt_tags,
                       video_category
                FROM code_prefix_movies
                WHERE COALESCE(video_category, '') = ''
                ORDER BY code
                '''
            )
            for row in cursor.fetchall():
                code = str(row[1] or '').strip().upper()
                if code in staged_codes:
                    continue
                if not is_javtxt_eligible_movie(
                    {
                        'code': code,
                        'title': row[2] or '',
                        'release_date': row[7] or '',
                        'javtxt_tags': row[8] or '',
                        'video_category': normalize_video_category(row[9]),
                    }
                ):
                    if str(row[4] or '').strip() or str(row[5] or '').strip() or str(row[6] or '').strip():
                        prefix_rowids_to_clear.append(row[0])
                    continue
                self._merge_manual_category_row(
                    manual_rows,
                    code=code,
                    title=row[2],
                    avfan_url=row[3],
                    javtxt_url=row[4],
                    author=row[5],
                    author_raw=row[6],
                    release_date=row[7],
                    javtxt_tags=row[8],
                    video_category=row[9],
                )

            cursor.execute(
                '''
                SELECT rowid,
                       code,
                       COALESCE(NULLIF(title, ''), code) AS display_title,
                       avfan_url,
                       javtxt_url,
                       author,
                       author_raw,
                       release_date,
                       javtxt_tags,
                       video_category
                FROM actor_movies
                WHERE COALESCE(video_category, '') = ''
                ORDER BY code
                '''
            )
            for row in cursor.fetchall():
                code = str(row[1] or '').strip().upper()
                if code in staged_codes:
                    continue
                if not is_javtxt_eligible_movie(
                    {
                        'code': code,
                        'title': row[2] or '',
                        'release_date': row[7] or '',
                        'javtxt_tags': row[8] or '',
                        'video_category': normalize_video_category(row[9]),
                    }
                ):
                    if str(row[4] or '').strip() or str(row[5] or '').strip() or str(row[6] or '').strip():
                        actor_rowids_to_clear.append(row[0])
                    continue
                self._merge_manual_category_row(
                    manual_rows,
                    code=code,
                    title=row[2],
                    avfan_url=row[3],
                    javtxt_url=row[4],
                    author=row[5],
                    author_raw=row[6],
                    release_date=row[7],
                    javtxt_tags=row[8],
                    video_category=row[9],
                )

            if processed_codes_to_clear:
                self._clear_processed_video_javtxt_codes(cursor, processed_codes_to_clear)
            if prefix_rowids_to_clear:
                self._clear_web_movie_javtxt_rowids(cursor, 'code_prefix_movies', prefix_rowids_to_clear)
            if actor_rowids_to_clear:
                self._clear_web_movie_javtxt_rowids(cursor, 'actor_movies', actor_rowids_to_clear)
            if processed_codes_to_clear or prefix_rowids_to_clear or actor_rowids_to_clear:
                conn.commit()
        return {
            'videos': [manual_rows[code] for code in sorted(manual_rows)],
            'staged_count': len(staged_rows),
        }

    def stage_video_category(self, code, category):
        normalized_code = standardize_video_code(code)
        normalized_category = normalize_video_category(category)
        if not normalized_code:
            raise ValueError('缺少视频编号')
        if normalized_category not in VIDEO_CATEGORY_OPTIONS:
            raise ValueError('视频分类无效')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT INTO manual_category_staging (code, category, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (normalized_code, normalized_category),
            )
            conn.commit()
            return {
                'staged_count': self._count_staged_video_categories(cursor),
            }

    def stage_video_categories(self, entries):
        normalized_entries = {}
        for entry in entries or []:
            code = standardize_video_code((entry or {}).get('code', ''))
            category = normalize_video_category((entry or {}).get('category', ''))
            if not code:
                continue
            if category not in VIDEO_CATEGORY_OPTIONS:
                raise ValueError('视频分类无效')
            normalized_entries[code] = category

        if not normalized_entries:
            return {
                'staged_count': 0,
                'batch_count': 0,
            }

        payload = [
            (code, category)
            for code, category in normalized_entries.items()
        ]
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                '''
                INSERT INTO manual_category_staging (code, category, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(code) DO UPDATE SET
                    category = excluded.category,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                payload,
            )
            conn.commit()
            return {
                'staged_count': self._count_staged_video_categories(cursor),
                'batch_count': len(payload),
            }

    def sync_staged_video_categories(self):
        with self._connect() as conn:
            cursor = conn.cursor()
            staged_rows = list(self._list_staged_video_categories(cursor).items())
            if not staged_rows:
                return {
                    'synced_count': 0,
                    'updated_count': 0,
                    'staged_count': 0,
                }

            update_payload = [(category, code) for code, category in staged_rows]
            updated_count = 0
            cursor.executemany(
                '''
                UPDATE processed_videos
                SET video_category = ?
                WHERE code = ?
                ''',
                update_payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.executemany(
                '''
                UPDATE code_prefix_movies
                SET video_category = ?
                WHERE code = ?
                ''',
                update_payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.executemany(
                '''
                UPDATE actor_movies
                SET video_category = ?
                WHERE code = ?
                ''',
                update_payload,
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.execute('DELETE FROM manual_category_staging')
            conn.commit()
            return {
                'synced_count': len(staged_rows),
                'updated_count': updated_count,
                'staged_count': 0,
            }

    def update_video_category(self, code, category):
        normalized_code = standardize_video_code(code)
        normalized_category = normalize_video_category(category)
        if not normalized_code:
            raise ValueError('缺少视频编号')
        if normalized_category not in VIDEO_CATEGORY_OPTIONS:
            raise ValueError('视频分类无效')

        with self._connect() as conn:
            cursor = conn.cursor()
            updated_count = 0
            cursor.execute(
                '''
                UPDATE processed_videos
                SET video_category = ?
                WHERE code = ?
                ''',
                (normalized_category, normalized_code),
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.execute(
                '''
                UPDATE code_prefix_movies
                SET video_category = ?
                WHERE code = ?
                ''',
                (normalized_category, normalized_code),
            )
            updated_count += int(cursor.rowcount or 0)
            cursor.execute(
                '''
                UPDATE actor_movies
                SET video_category = ?
                WHERE code = ?
                ''',
                (normalized_category, normalized_code),
            )
            updated_count += int(cursor.rowcount or 0)
            conn.commit()
            return updated_count

    @staticmethod
    def _list_staged_video_categories(cursor):
        cursor.execute(
            '''
            SELECT code, category
            FROM manual_category_staging
            ORDER BY updated_at, code
            '''
        )
        return {
            standardize_video_code(row[0]): normalize_video_category(row[1])
            for row in cursor.fetchall()
            if standardize_video_code(row[0])
        }

    @staticmethod
    def _count_staged_video_categories(cursor):
        cursor.execute('SELECT COUNT(*) FROM manual_category_staging')
        row = cursor.fetchone()
        return int((row or [0])[0] or 0)

    @staticmethod
    def _merge_manual_category_row(
        rows_by_code,
        code,
        title,
        avfan_url,
        javtxt_url,
        author='',
        author_raw='',
        release_date='',
        javtxt_tags='',
        video_category='',
    ):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return
        if not is_javtxt_eligible_movie(
            {
                'code': normalized_code,
                'title': title,
                'release_date': release_date,
                'javtxt_tags': javtxt_tags,
                'video_category': normalize_video_category(video_category),
            }
        ):
            return

        if not is_manual_category_candidate(
            {
                'author': author,
                'author_raw': author_raw,
                'javtxt_url': javtxt_url,
            }
        ):
            return

        manual_tier = VideoDatabase._classify_manual_category_tier(author, author_raw)
        if not manual_tier:
            return

        current = rows_by_code.get(normalized_code)
        candidate = {
            'code': normalized_code,
            'title': str(title or '').strip() or normalized_code,
            'avfan_url': str(avfan_url or '').strip(),
            'javtxt_url': str(javtxt_url or '').strip(),
            'javtxt_tags': str(javtxt_tags or '').strip(),
            'javtxt_enrichment_status': ENRICHED_STATUS,
            'manual_tier': manual_tier,
            'actor_count': count_video_actors(author),
        }
        if current is None:
            rows_by_code[normalized_code] = candidate
            return

        if not current.get('avfan_url') and candidate['avfan_url']:
            current['avfan_url'] = candidate['avfan_url']
        if not current.get('javtxt_url') and candidate['javtxt_url']:
            current['javtxt_url'] = candidate['javtxt_url']
        if not current.get('manual_tier') and candidate['manual_tier']:
            current['manual_tier'] = candidate['manual_tier']
            current['actor_count'] = candidate['actor_count']
        if not current.get('javtxt_tags') and candidate['javtxt_tags']:
            current['javtxt_tags'] = candidate['javtxt_tags']
        if (
            current.get('title', '').strip().upper() == normalized_code
            or len(current.get('title', '')) < len(candidate['title'])
        ):
            current['title'] = candidate['title']

    @staticmethod
    def _classify_manual_category_tier(author='', author_raw=''):
        tier = classify_manual_category_tier(author, author_raw)
        if tier in (
            MANUAL_CATEGORY_TIER_FIRST,
            MANUAL_CATEGORY_TIER_SECOND,
            MANUAL_CATEGORY_TIER_THIRD,
        ):
            return tier
        return ''

    def get_javtxt_actor_cache_by_codes(self, codes):
        normalized_codes = []
        seen = set()
        for code in codes or []:
            normalized_code = standardize_video_code(code)
            if not normalized_code or normalized_code in seen:
                continue
            seen.add(normalized_code)
            normalized_codes.append(normalized_code)

        if not normalized_codes:
            return {}

        placeholders = ','.join('?' for _ in normalized_codes)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT code, javtxt_actors, javtxt_actors_raw, javtxt_movie_id, javtxt_url,
                       javtxt_tags, javtxt_enrichment_status, javtxt_release_date, release_date
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
                'javtxt_actors_raw': row[2] or '',
                'javtxt_movie_id': row[3] or '',
                'javtxt_url': row[4] or '',
                'javtxt_tags': row[5] or '',
                'javtxt_enrichment_status': row[6] or UNENRICHED_STATUS,
                'javtxt_release_date': row[7] or '',
                'release_date': row[8] or '',
            }
            for row in rows
        }

    def _is_processed_video_javtxt_eligible(self, cursor, code, info=None):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return False

        cursor.execute(
            '''
            SELECT COALESCE(NULLIF(javtxt_title, ''), NULLIF(title, ''), code),
                   release_date,
                   javtxt_tags,
                   video_category,
                   javtxt_release_date
            FROM processed_videos
            WHERE code = ?
            ''',
            (normalized_code,),
        )
        row = cursor.fetchone() or ('', '', '', '', '')
        candidate = {
            'code': normalized_code,
            'title': str((info or {}).get('javtxt_title', (info or {}).get('title', row[0] or normalized_code)) or '').strip(),
            'release_date': str((info or {}).get('release_date', row[1] or '') or '').strip(),
            'javtxt_tags': str((info or {}).get('javtxt_tags', row[2] or '') or '').strip(),
            'video_category': normalize_video_category((info or {}).get('video_category', row[3] or '')),
            'javtxt_release_date': str((info or {}).get('release_date', row[4] or '') or '').strip(),
        }
        return is_javtxt_eligible_movie(candidate)

    def _update_processed_video_javtxt_metadata(self, cursor, code, info=None):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return
        info = dict(info or {})
        cursor.execute(
            '''
            UPDATE processed_videos
            SET title = COALESCE(NULLIF(?, ''), title),
                javtxt_title = COALESCE(NULLIF(?, ''), javtxt_title),
                release_date = COALESCE(NULLIF(?, ''), release_date),
                maker = COALESCE(NULLIF(?, ''), maker),
                publisher = COALESCE(NULLIF(?, ''), publisher),
                javtxt_tags = COALESCE(NULLIF(?, ''), javtxt_tags),
                javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date)
            WHERE code = ?
            ''',
            (
                str(info.get('title', info.get('javtxt_title', '')) or '').strip(),
                str(info.get('javtxt_title', info.get('title', '')) or '').strip(),
                str(info.get('release_date', '') or '').strip(),
                join_values(info.get('maker')),
                join_values(info.get('publisher')),
                str(info.get('javtxt_tags', '') or '').strip(),
                str(info.get('release_date', '') or '').strip(),
                normalized_code,
            ),
        )

    @staticmethod
    def _resolve_ineligible_javtxt_status(status):
        normalized_status = str(status or '').strip()
        if is_no_result_status(normalized_status):
            return normalized_status
        return NO_SEARCH_RESULTS_STATUS

    def _mark_processed_video_javtxt_ineligible(self, cursor, code, status, error=''):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return
        cursor.execute(
            '''
            UPDATE processed_videos
            SET javtxt_movie_id = '',
                javtxt_url = '',
                javtxt_actors = '',
                javtxt_actors_raw = '',
                javtxt_enrichment_status = ?,
                javtxt_enrichment_error = ?,
                javtxt_enriched_at = CURRENT_TIMESTAMP
            WHERE code = ?
            ''',
            (
                self._resolve_ineligible_javtxt_status(status),
                str(error or '').strip() or JAVTXT_INELIGIBLE_ERROR,
                normalized_code,
            ),
        )

    def _clear_processed_video_javtxt_state(self, cursor, code):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return
        cursor.execute(
            '''
            UPDATE processed_videos
            SET javtxt_movie_id = '',
                javtxt_url = '',
                javtxt_title = '',
                javtxt_actors = '',
                javtxt_actors_raw = '',
                javtxt_tags = '',
                javtxt_enrichment_status = ?,
                javtxt_enrichment_error = '',
                javtxt_enriched_at = NULL
            WHERE code = ?
            ''',
            (UNENRICHED_STATUS, normalized_code),
        )

    def save_javtxt_cache_for_video(self, code, info, status=ENRICHED_STATUS, error=''):
        normalized_code = standardize_video_code(code)
        if not normalized_code:
            return 0
        payload = dict(info or {})
        if error and not payload.get('error'):
            payload['error'] = error
        normalized_javtxt = self._normalize_processed_video_javtxt_payload(payload, status)

        with self._connect() as conn:
            cursor = conn.cursor()
            if not self._is_processed_video_javtxt_eligible(cursor, normalized_code, info):
                self._update_processed_video_javtxt_metadata(cursor, normalized_code, info)
                self._refresh_video_category(
                    cursor,
                    normalized_code,
                    tags_text=normalized_javtxt['sanitized_javtxt_tags'],
                    actors_text=normalized_javtxt['sanitized_javtxt_actors'] or normalized_javtxt['sanitized_author'],
                )
                self._mark_processed_video_javtxt_ineligible(
                    cursor,
                    normalized_code,
                    normalized_javtxt['status'],
                    normalized_javtxt['error'],
                )
                self._refresh_combined_video_status(
                    cursor,
                    normalized_code,
                    normalized_javtxt['error'] or JAVTXT_INELIGIBLE_ERROR,
                )
                self._propagate_processed_video_javtxt_state_for_codes(cursor, [normalized_code])
                conn.commit()
                self._refresh_web_movie_parent_javtxt_statuses_for_codes([normalized_code])
                return 0
            cursor.execute(
                '''
                UPDATE processed_videos
                SET javtxt_movie_id = COALESCE(NULLIF(?, ''), javtxt_movie_id),
                    javtxt_url = COALESCE(NULLIF(?, ''), javtxt_url),
                    javtxt_title = COALESCE(NULLIF(?, ''), javtxt_title),
                    javtxt_actors = ?,
                    javtxt_actors_raw = ?,
                    javtxt_tags = COALESCE(NULLIF(?, ''), javtxt_tags),
                    release_date = COALESCE(NULLIF(?, ''), release_date),
                    javtxt_release_date = COALESCE(NULLIF(?, ''), javtxt_release_date),
                    javtxt_enrichment_status = ?,
                    javtxt_enrichment_error = ?,
                    javtxt_enriched_at = CURRENT_TIMESTAMP
                WHERE code = ?
                ''',
                (
                    normalized_javtxt['javtxt_movie_id'],
                    normalized_javtxt['javtxt_url'],
                    normalized_javtxt['javtxt_title'],
                    normalized_javtxt['sanitized_javtxt_actors'],
                    normalized_javtxt['raw_javtxt_actors'],
                    normalized_javtxt['sanitized_javtxt_tags'],
                    normalized_javtxt['release_date'],
                    normalized_javtxt['release_date'],
                    normalized_javtxt['status'],
                    normalized_javtxt['error'],
                    normalized_code,
                ),
            )
            updated_count = int(cursor.rowcount or 0)
            self._refresh_video_category(
                cursor,
                normalized_code,
                tags_text=normalized_javtxt['sanitized_javtxt_tags'],
                actors_text=normalized_javtxt['sanitized_javtxt_actors'],
            )
            self._refresh_combined_video_status(cursor, normalized_code, normalized_javtxt['error'])
            self._propagate_processed_video_javtxt_state_for_codes(cursor, [normalized_code])
            conn.commit()
        self._refresh_web_movie_parent_javtxt_statuses_for_codes([normalized_code])
        return updated_count

    def import_local_videos(self, records):
        normalized_records = {}
        for record in records or []:
            code = standardize_video_code((record or {}).get('code', ''))
            if not code:
                continue
            normalized_records[code] = {
                'code': code,
                'storage_location': str((record or {}).get('storage_location', '') or '').strip(),
                'duration': str((record or {}).get('duration', '') or '').strip(),
                'size': str((record or {}).get('size', '') or '').strip(),
            }

        if not normalized_records:
            return 0

        codes = list(normalized_records.keys())
        existing_records = self.get_videos_by_codes(codes)
        new_records = [normalized_records[code] for code in codes if code not in existing_records]
        existing_updates = [normalized_records[code] for code in codes if code in existing_records]

        with self._connect() as conn:
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
                    VALUES (?, '', '', ?, ?, ?, ?, ?, ?)
                    ''',
                    [
                        (
                            record['code'],
                            record['duration'],
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
                    SET duration = CASE WHEN ? <> '' THEN ? ELSE duration END,
                        size = CASE WHEN ? <> '' THEN ? ELSE size END,
                        storage_location = CASE WHEN ? <> '' THEN ? ELSE storage_location END
                    WHERE code = ?
                    ''',
                    [
                        (
                            record['duration'],
                            record['duration'],
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

    def list_ladder_entries(self, board_key=None, entity_type=None):
        normalized_board_key = normalize_ladder_board_key(board_key)
        normalized_entity_type = normalize_ladder_entity_type(entity_type)
        clauses = []
        params = []
        if normalized_board_key:
            clauses.append('board_key = ?')
            params.append(normalized_board_key)
        if normalized_entity_type:
            clauses.append('entity_type = ?')
            params.append(normalized_entity_type)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f'''
                SELECT board_key, entity_type, entity_name, tier, medal, created_at, updated_at
                FROM ladder_entries
                {where_sql}
                ORDER BY updated_at DESC, entity_name
                ''',
                params,
            )
            return [
                {
                    'board_key': row[0] or '',
                    'entity_type': row[1] or '',
                    'entity_name': row[2] or '',
                    'tier': row[3] or '',
                    'medal': row[4] or '',
                    'created_at': row[5] or '',
                    'updated_at': row[6] or '',
                }
                for row in cursor.fetchall()
            ]

    def save_ladder_entry(self, board_key, entity_type, entity_name, tier):
        normalized_board_key = normalize_ladder_board_key(board_key)
        normalized_entity_type = normalize_ladder_entity_type(entity_type)
        normalized_name = str(entity_name or '').strip()
        normalized_tier = normalize_ladder_tier(tier)
        if not normalized_entity_type:
            raise ValueError('缺少榜单类型')
        if not normalized_name:
            raise ValueError('缺少榜单名称')
        if not normalized_tier:
            raise ValueError('缺少榜单等级')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                INSERT OR IGNORE INTO ladder_entries (
                    board_key, entity_type, entity_name, tier, medal, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ''',
                (normalized_board_key, normalized_entity_type, normalized_name, normalized_tier),
            )
            cursor.execute(
                '''
                UPDATE ladder_entries
                SET tier = ?, updated_at = CURRENT_TIMESTAMP
                WHERE board_key = ? AND entity_type = ? AND entity_name = ?
                ''',
                (normalized_tier, normalized_board_key, normalized_entity_type, normalized_name),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def update_ladder_entry_medal(self, board_key, entity_type, entity_name, medal):
        normalized_board_key = normalize_ladder_board_key(board_key)
        normalized_entity_type = normalize_ladder_entity_type(entity_type)
        normalized_name = str(entity_name or '').strip()
        if not normalized_entity_type:
            raise ValueError('缺少榜单类型')
        if not normalized_name:
            raise ValueError('缺少榜单名称')

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''
                UPDATE ladder_entries
                SET medal = ?, updated_at = CURRENT_TIMESTAMP
                WHERE board_key = ? AND entity_type = ? AND entity_name = ?
                ''',
                (str(medal or '').strip(), normalized_board_key, normalized_entity_type, normalized_name),
            )
            if int(cursor.rowcount or 0) <= 0:
                raise ValueError('未找到对应入选者')
            conn.commit()
            return int(cursor.rowcount or 0)

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

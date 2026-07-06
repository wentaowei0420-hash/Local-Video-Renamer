from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIR.parent
ENV_FILE = PROJECT_ROOT / '.env'
ENV_EXAMPLE_FILE = PROJECT_ROOT / '.env.example'
ENRICHMENT_SETTINGS_FILE = PROJECT_ROOT / '.enrichment_settings.json'
VIDEO_LIBRARY_SETTINGS_FILE = PROJECT_ROOT / '.video_library_settings.json'
VIDEO_FILTER_SETTINGS_FILE = PROJECT_ROOT / '.video_filter_settings.json'
ACTOR_LIBRARY_SETTINGS_FILE = PROJECT_ROOT / '.actor_library_settings.json'
CODE_PREFIX_LIBRARY_SETTINGS_FILE = PROJECT_ROOT / '.code_prefix_library_settings.json'
SNAPSHOT_RUNTIME_DIR = PROJECT_ROOT / 'runtime_snapshots'
DATA_CENTER_SNAPSHOT_FILE = SNAPSHOT_RUNTIME_DIR / 'data_center_snapshot.json'
CODE_PREFIX_SNAPSHOT_FILE = SNAPSHOT_RUNTIME_DIR / 'code_prefix_snapshot.json'
ACTOR_SNAPSHOT_FILE = SNAPSHOT_RUNTIME_DIR / 'actor_snapshot.json'
SNAPSHOT_REFRESH_LOG_FILE = SNAPSHOT_RUNTIME_DIR / 'snapshot_refresh.log'
LEGACY_DATA_CENTER_SNAPSHOT_FILE = PROJECT_ROOT / '.data_center_snapshot.json'
LEGACY_CODE_PREFIX_SNAPSHOT_FILE = PROJECT_ROOT / '.code_prefix_snapshot.json'
DATABASE_FILE = PROJECT_ROOT / 'video_database.db'
BROWSER_PROFILES_DIR = PROJECT_ROOT / 'browser_profiles'
AVFAN_PROFILE_DIR = BROWSER_PROFILES_DIR / 'avfan'
COMBO_TASK_LOG_DIR = PROJECT_ROOT / 'combo_task_logs'
TASK_TRACE_LOG_DIR = PROJECT_ROOT / 'task_logs'
COMBO_BROWSER_PROFILES_DIR = BROWSER_PROFILES_DIR / 'combo'

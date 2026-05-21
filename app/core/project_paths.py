from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIR.parent
ENV_FILE = PROJECT_ROOT / '.env'
ENV_EXAMPLE_FILE = PROJECT_ROOT / '.env.example'
ENRICHMENT_SETTINGS_FILE = PROJECT_ROOT / '.enrichment_settings.json'
DATABASE_FILE = PROJECT_ROOT / 'video_database.db'
BROWSER_PROFILES_DIR = PROJECT_ROOT / 'browser_profiles'
AVFAN_PROFILE_DIR = BROWSER_PROFILES_DIR / 'avfan'
VIDEO_CSV_FILE = PROJECT_ROOT / '目录统计 - 详细介绍.csv'
ACTOR_CSV_FILE = PROJECT_ROOT / '目录统计 - 演员统计.csv'

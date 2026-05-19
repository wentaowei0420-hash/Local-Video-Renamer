import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = BASE_DIR / '.env'


def load_env_file(env_path=None):
    env_path = Path(env_path) if env_path else DEFAULT_ENV_PATH
    values = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def get_setting(key, default=None, required=False, env_path=None):
    env_values = load_env_file(env_path)
    value = os.environ.get(key, env_values.get(key, default))
    if required and (value is None or str(value).strip() == ''):
        raise RuntimeError(f'缺少配置项 {key}，请在 .env 中设置。')
    return value

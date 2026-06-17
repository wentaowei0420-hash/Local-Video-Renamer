from pathlib import Path
from urllib.parse import quote, urlparse

from app.core.app_config import get_setting
from app.core.project_paths import PROJECT_ROOT


def _get_text_setting(key, default='', required=False):
    value = str(get_setting(key, default=default, required=required) or '').strip()
    if required and not value:
        raise RuntimeError(f'缺少配置项 {key}，请在 .env 中设置。')
    return value or str(default or '').strip()


def get_int_setting(key, default=0, required=False):
    value = _get_text_setting(key, default=str(default), required=required)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f'配置项 {key} 必须是整数，当前值: {value!r}') from exc


def get_bool_setting(key, default=False):
    value = _get_text_setting(key, default='true' if default else 'false')
    return value.lower() in {'1', 'true', 'yes', 'on'}


def get_path_setting(key, default_relative_path):
    value = _get_text_setting(key, default=str(default_relative_path))
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def get_backend_host():
    return _get_text_setting('BACKEND_BIND_HOST', required=True)


def get_backend_port():
    return get_int_setting('BACKEND_PORT', required=True)


def get_backend_base_url():
    explicit = _get_text_setting('BACKEND_BASE_URL', default='')
    if explicit:
        return explicit.rstrip('/')
    return f'http://{get_backend_host()}:{get_backend_port()}'


def get_backend_timeout_seconds():
    return get_int_setting('BACKEND_TIMEOUT_SECONDS', default=30)


def get_scraper_locale():
    return _get_text_setting('SCRAPER_LOCALE', default='zh-CN')


def get_scraper_browser_channel():
    return _get_text_setting('SCRAPER_BROWSER_CHANNEL', default='chrome')


def get_browser_profiles_dir():
    return get_path_setting('BROWSER_PROFILES_DIR', 'browser_profiles')


def get_avfan_profile_dir():
    value = _get_text_setting('AVFAN_PROFILE_DIR', default='')
    if value:
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return get_browser_profiles_dir() / 'avfan'


def get_avfan_base_url():
    explicit = _get_text_setting('AVFAN_BASE_URL', default='')
    if explicit:
        return explicit.rstrip('/')
    home_url = _get_text_setting('SCRAPER_HOME_URL', required=True)
    parsed = urlparse(home_url)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError('SCRAPER_HOME_URL 不是有效的网址。')
    return f'{parsed.scheme}://{parsed.netloc}'


def get_avfan_actor_search_url(actor_name):
    template = _get_text_setting('AVFAN_ACTOR_SEARCH_URL_TEMPLATE', required=True)
    return template.format(
        base_url=get_avfan_base_url(),
        query=quote(str(actor_name or '').strip()),
    )


def get_avfan_actor_page_url(actor_id):
    normalized_actor_id = quote(str(actor_id or '').strip())
    if not normalized_actor_id:
        raise RuntimeError('actor_id 不能为空')
    return f'{get_avfan_base_url()}/casts/{normalized_actor_id}'


def get_avfan_code_prefix_url(prefix, page_number):
    template = _get_text_setting('AVFAN_CODE_PREFIX_URL_TEMPLATE', required=True)
    return template.format(
        base_url=get_avfan_base_url(),
        prefix=quote(str(prefix or '').strip().upper()),
        page=int(page_number or 1),
    )


def get_javtxt_base_url():
    return _get_text_setting('JAVTXT_BASE_URL', required=True).rstrip('/')


def get_javtxt_search_url(normalized_code):
    template = _get_text_setting('JAVTXT_SEARCH_URL_TEMPLATE', required=True)
    return template.format(
        base_url=get_javtxt_base_url(),
        code=str(normalized_code or '').strip().upper(),
    )


def get_probe_target_url():
    return _get_text_setting('PROBE_TARGET_URL', default='')


def get_probe_show_browser():
    return get_bool_setting('PROBE_SHOW_BROWSER', default=True)


def get_probe_max_lines():
    return get_int_setting('PROBE_MAX_LINES', default=820)


def get_probe_max_entries():
    return get_int_setting('PROBE_MAX_ENTRIES', default=90)

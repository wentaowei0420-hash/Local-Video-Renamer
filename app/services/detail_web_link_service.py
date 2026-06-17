from app.core.runtime_config import (
    get_avfan_actor_page_url,
    get_avfan_actor_search_url,
    get_avfan_code_prefix_url,
)


def build_actor_detail_web_url(actor_name, actor_id=''):
    normalized_actor_id = str(actor_id or '').strip()
    if normalized_actor_id:
        return get_avfan_actor_page_url(normalized_actor_id)
    return get_avfan_actor_search_url(actor_name)


def build_code_prefix_detail_web_url(prefix):
    return get_avfan_code_prefix_url(prefix, 1)

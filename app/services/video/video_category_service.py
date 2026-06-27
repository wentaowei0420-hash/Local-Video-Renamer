from app.core.second_source_actor_text import is_unpublished_actor_text
from app.services.identity import split_actor_names


VIDEO_CATEGORY_SINGLE = '单体作品'
VIDEO_CATEGORY_CO_STAR = '共演作品'
VIDEO_CATEGORY_COLLECTION = '合集作品'

MANUAL_CATEGORY_TIER_FIRST = 'tier_1'
MANUAL_CATEGORY_TIER_SECOND = 'tier_2'
MANUAL_CATEGORY_TIER_THIRD = 'tier_3'

VIDEO_CATEGORY_OPTIONS = (
    VIDEO_CATEGORY_SINGLE,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_COLLECTION,
)

COLLECTION_TAG_KEYWORDS = (
    '精选合集',
    '四小时以上作品',
    '16時間以上',
    '16時間以上作品',
    '16时间以上',
    '16时间以上作品',
    '16小时以上',
    '16小时以上作品',
    '福袋',
)


def normalize_video_category(value):
    text = str(value or '').strip()
    return text if text in VIDEO_CATEGORY_OPTIONS else ''


def detect_video_category(tags_text='', actors_text='', force_single_or_co_star=False):
    normalized_tags = str(tags_text or '').strip()
    if any(keyword in normalized_tags for keyword in COLLECTION_TAG_KEYWORDS):
        return VIDEO_CATEGORY_COLLECTION

    actor_names = split_actor_names(actors_text)
    if len(actor_names) == 1:
        return VIDEO_CATEGORY_SINGLE
    if force_single_or_co_star:
        return VIDEO_CATEGORY_CO_STAR

    return ''


def requires_manual_video_category(tags_text='', actors_text='', force_single_or_co_star=False):
    return not bool(detect_video_category(tags_text, actors_text, force_single_or_co_star=force_single_or_co_star))


def count_video_actors(actors_text=''):
    return len(split_actor_names(actors_text))


def classify_manual_category_tier(actors_text='', author_raw=''):
    if is_unpublished_actor_text(author_raw):
        return MANUAL_CATEGORY_TIER_THIRD

    actor_count = count_video_actors(actors_text)
    if actor_count <= 0:
        return ''
    if actor_count > 4:
        return MANUAL_CATEGORY_TIER_FIRST
    return MANUAL_CATEGORY_TIER_SECOND

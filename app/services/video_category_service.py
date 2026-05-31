from app.services.actor_identifier import split_actor_names


VIDEO_CATEGORY_SINGLE = '单体作品'
VIDEO_CATEGORY_CO_STAR = '共演作品'
VIDEO_CATEGORY_COLLECTION = '合集作品'

VIDEO_CATEGORY_OPTIONS = (
    VIDEO_CATEGORY_SINGLE,
    VIDEO_CATEGORY_CO_STAR,
    VIDEO_CATEGORY_COLLECTION,
)

COLLECTION_TAG_KEYWORDS = (
    '精选合集',
    '四小时以上作品',
    '16時間以上',
    '福袋',
)


def normalize_video_category(value):
    text = str(value or '').strip()
    return text if text in VIDEO_CATEGORY_OPTIONS else ''


def detect_video_category(tags_text='', actors_text=''):
    normalized_tags = str(tags_text or '').strip()
    if any(keyword in normalized_tags for keyword in COLLECTION_TAG_KEYWORDS):
        return VIDEO_CATEGORY_COLLECTION

    actor_names = split_actor_names(actors_text)
    if len(actor_names) == 1:
        return VIDEO_CATEGORY_SINGLE

    return ''


def requires_manual_video_category(tags_text='', actors_text=''):
    return not bool(detect_video_category(tags_text, actors_text))

import re


_SUBSTANTIVE_ACTOR_TEXT_RE = re.compile(r'[A-Za-z0-9\u4e00-\u9fffぁ-んァ-ヴー]')


_MISSING_ACTOR_TEXTS = {
    '',
    '-',
    '--',
    'na',
    'n/a',
    'none',
    'null',
    'unknown',
    '无',
    '無',
    '暂无',
    '暫無',
    '未知',
    '无记录',
    '無記錄',
    '未公开',
    '未公開',
}

_UNPUBLISHED_ACTOR_TEXTS = {
    '未公开',
    '未公開',
}


def normalize_second_source_actor_text(value):
    text = _normalize_spacing(value)
    if not text:
        return ''
    compact = re.sub(r'[\s\u3000,，、/;；|]+', '', text).lower()
    if compact in _MISSING_ACTOR_TEXTS:
        return ''
    if not _SUBSTANTIVE_ACTOR_TEXT_RE.search(text):
        return ''
    return text


def is_unpublished_actor_text(value):
    text = _normalize_spacing(value)
    if not text:
        return False
    compact = re.sub(r'[\s\u3000,，、/;；|]+', '', text)
    return compact in _UNPUBLISHED_ACTOR_TEXTS


def _normalize_spacing(value):
    return ' '.join(str(value or '').replace('\u3000', ' ').split()).strip()

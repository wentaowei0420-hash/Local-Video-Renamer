import re


ALNUM_RE = re.compile(r'[^A-Z0-9]+')
LEADING_DIGIT_VENDOR_CODE_RE = re.compile(r'^\d+([A-Z]+)(\d+)$')
COMPACT_CODE_RE = re.compile(r'^([A-Z]+)(\d+)$')
SEPARATED_CODE_RE = re.compile(r'^([A-Z0-9]+)[-_ ]+(\d+)$')


def standardize_video_code(value):
    text = str(value or '').strip().upper()
    if not text:
        return ''

    separated = SEPARATED_CODE_RE.match(text)
    if separated:
        prefix = ALNUM_RE.sub('', separated.group(1))
        number = separated.group(2)
        leading_digit_prefix = re.match(r'^\d+([A-Z][A-Z0-9]*)$', prefix)
        if leading_digit_prefix:
            prefix = leading_digit_prefix.group(1)
        if any(char.isalpha() for char in prefix):
            return f'{prefix}-{number}'
        return ALNUM_RE.sub('-', text).strip('-')

    compact = ALNUM_RE.sub('', text)
    match = LEADING_DIGIT_VENDOR_CODE_RE.match(compact)
    if match:
        return f'{match.group(1)}-{match.group(2)}'

    match = COMPACT_CODE_RE.match(compact)
    if match:
        return f'{match.group(1)}-{match.group(2)}'

    return ALNUM_RE.sub('-', text).strip('-')


def compact_video_code(value):
    return ALNUM_RE.sub('', standardize_video_code(value))


def has_supported_video_code(value):
    standardized = standardize_video_code(value)
    if not standardized:
        return False
    prefix = standardized.split('-', 1)[0]
    return any(char.isalpha() for char in prefix)

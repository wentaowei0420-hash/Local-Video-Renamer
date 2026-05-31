import re

from app.core.video_code import standardize_video_code
from app.core.video_filename_builder import build_video_filename


DEFAULT_VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.wmv', '.mov')
TITLE_EDGE_CHARS = r'\s\-_【】\[\]{}()（）《》>\"\'“”‘’.,。？！!?~、；;:：'
VIDEO_SUFFIX_RE = re.compile(r'\.(mp4|mkv|avi|wmv|mov)\s*$', re.I)


def strip_title_suffix_noise(title):
    previous = None
    clean_title = str(title or '')
    while clean_title != previous:
        previous = clean_title
        clean_title = VIDEO_SUFFIX_RE.sub('', clean_title)
        clean_title = re.sub(
            rf'^[{TITLE_EDGE_CHARS}]+|[{TITLE_EDGE_CHARS}]+$',
            '',
            clean_title,
        )
    return clean_title.strip()


def normalize_text_spacing(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def clean_video_title(code, author, raw_name):
    clean_title = re.sub(re.escape(code or ''), '', str(raw_name or ''), flags=re.I) if code else str(raw_name or '')
    if author:
        clean_title = clean_title.replace(author, '')

    clean_title = normalize_text_spacing(strip_title_suffix_noise(clean_title))

    if not clean_title:
        clean_title = normalize_text_spacing(strip_title_suffix_noise(raw_name))

    return clean_title


def extract_code_from_filename(filename):
    match = re.search(r'(\d*[a-zA-Z]+)[-_ ]?(\d+)', str(filename or ''))
    if match:
        return standardize_video_code(f'{match.group(1)}{match.group(2)}')
    return None


def build_normalized_filename(metadata, extension):
    return build_video_filename(metadata, extension)

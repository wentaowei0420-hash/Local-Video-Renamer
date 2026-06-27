from datetime import date

from app.core.second_source_actor_text import normalize_second_source_actor_text


UNKNOWN_ACTOR_AGE_TEXT = '未知'


def has_known_actor_birthday(value):
    return bool(normalize_second_source_actor_text(value))


def normalize_actor_birthday_for_display(value):
    text = str(value or '').strip()
    if not text:
        return ''
    if not has_known_actor_birthday(text):
        return text
    try:
        parsed = _parse_actor_birthday(text)
    except ValueError:
        return text
    return f'{parsed.year}/{parsed.month}/{parsed.day}'


def normalize_actor_birthday_for_storage(value):
    text = str(value or '').strip()
    if not text:
        return ''
    if not has_known_actor_birthday(text):
        return text
    try:
        return _parse_actor_birthday(text).isoformat()
    except ValueError:
        return text


def normalize_actor_age_for_display(age, birthday):
    age_text = str(age or '').strip()
    if not has_known_actor_birthday(birthday):
        return UNKNOWN_ACTOR_AGE_TEXT
    if normalize_second_source_actor_text(age_text):
        return age_text
    try:
        birthday_date = _parse_actor_birthday(birthday)
    except ValueError:
        return UNKNOWN_ACTOR_AGE_TEXT
    return str(_calculate_actor_age_from_birthday(birthday_date))


def _parse_actor_birthday(value):
    text = str(value or '').strip()
    if '/' in text:
        year_text, month_text, day_text = text.split('/')
        return date(int(year_text), int(month_text), int(day_text))
    return date.fromisoformat(text)


def _calculate_actor_age_from_birthday(birthday):
    today = date.today()
    age = today.year - birthday.year
    if (today.month, today.day) < (birthday.month, birthday.day):
        age -= 1
    return max(age, 0)

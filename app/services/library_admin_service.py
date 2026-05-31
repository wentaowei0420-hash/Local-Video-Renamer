import re

from app.core.video_code import standardize_video_code
from app.services.actor_identifier import is_ignored_actor_name, normalize_actor_name, split_actor_names
from app.services.code_prefix_library import CodePrefixLibrary, extract_code_prefix


CODE_PREFIX_RE = re.compile(r'^[A-Z0-9]+$')


class LibraryAdminService:
    def __init__(self, database):
        self.database = database
        self.code_prefix_library = CodePrefixLibrary(database)

    def rename_code_prefix(self, old_prefix, new_prefix):
        normalized_old_prefix = normalize_code_prefix(old_prefix)
        normalized_new_prefix = normalize_code_prefix(new_prefix)
        if not normalized_old_prefix or not normalized_new_prefix:
            raise ValueError('番号前缀不能为空')
        if normalized_old_prefix == normalized_new_prefix:
            return 0

        visible_prefixes = {
            str(row.get('prefix', '')).strip().upper()
            for row in self.code_prefix_library.list_prefixes()
        }
        if normalized_old_prefix not in visible_prefixes:
            raise ValueError(f'未找到番号前缀：{normalized_old_prefix}')
        if normalized_new_prefix in visible_prefixes:
            raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在')

        hidden_prefixes = set()
        if hasattr(self.database, 'list_hidden_code_prefixes'):
            hidden_prefixes = self.database.list_hidden_code_prefixes()
        if normalized_new_prefix in hidden_prefixes:
            raise ValueError(f'番号前缀 {normalized_new_prefix} 已被删除，请换一个前缀名称')

        enrichment_records = {}
        if hasattr(self.database, 'list_code_prefix_enrichment_records'):
            enrichment_records = self.database.list_code_prefix_enrichment_records()
        if normalized_new_prefix in enrichment_records:
            raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在补全记录')

        web_movies = list(self.database.list_code_prefix_movies(normalized_new_prefix))
        if web_movies:
            raise ValueError(f'番号前缀 {normalized_new_prefix} 已存在网页作品记录')

        code_updates = []
        for row in self.database.list_videos():
            code = standardize_video_code(row.get('code', ''))
            if extract_code_prefix(code) != normalized_old_prefix:
                continue
            code_updates.append((
                code,
                replace_code_prefix_in_code(code, normalized_old_prefix, normalized_new_prefix),
            ))

        if not code_updates:
            raise ValueError(f'未找到属于 {normalized_old_prefix} 的本地番号')

        web_movie_updates = []
        for movie in self.database.list_code_prefix_movies(normalized_old_prefix):
            old_code = standardize_video_code(movie.get('code', ''))
            if not old_code:
                continue
            web_movie_updates.append((
                old_code,
                replace_code_prefix_in_code(old_code, normalized_old_prefix, normalized_new_prefix),
            ))

        return self.database.rename_code_prefix(
            normalized_old_prefix,
            normalized_new_prefix,
            code_updates=code_updates,
            web_movie_updates=web_movie_updates,
        )

    def delete_code_prefix(self, prefix):
        normalized_prefix = normalize_code_prefix(prefix)
        if not normalized_prefix:
            raise ValueError('番号前缀不能为空')

        visible_prefixes = {
            str(row.get('prefix', '')).strip().upper()
            for row in self.code_prefix_library.list_prefixes()
        }
        if normalized_prefix not in visible_prefixes:
            raise ValueError(f'未找到番号前缀：{normalized_prefix}')

        return self.database.delete_code_prefix(normalized_prefix)

    def rename_actor(self, old_name, new_name):
        normalized_old_name = normalize_actor_name(old_name)
        normalized_new_name = normalize_actor_name(new_name)
        if not normalized_old_name or not normalized_new_name:
            raise ValueError('演员名称不能为空')
        if is_ignored_actor_name(normalized_new_name):
            raise ValueError('这个演员名称不可用')
        if normalized_old_name == normalized_new_name:
            return 0

        actor_names = {
            str(row.get('name', '')).strip()
            for row in self.database.list_actors()
        }
        if normalized_old_name not in actor_names:
            raise ValueError(f'未找到演员：{normalized_old_name}')
        if normalized_new_name in actor_names:
            raise ValueError(f'演员 {normalized_new_name} 已存在')

        if self.database.list_actor_movies(normalized_new_name):
            raise ValueError(f'演员 {normalized_new_name} 已存在网页作品记录')

        enrichment_record = self.database.get_actor_enrichment_record(normalized_new_name)
        if any(str(enrichment_record.get(field, '')).strip() for field in ('actor_id', 'enrichment_status', 'last_error', 'last_enriched_at')):
            raise ValueError(f'演员 {normalized_new_name} 已存在补全记录')
        if int(enrichment_record.get('avfan_total_pages', 0) or 0) > 0 or int(enrichment_record.get('avfan_total_videos', 0) or 0) > 0:
            raise ValueError(f'演员 {normalized_new_name} 已存在补全记录')

        author_updates = []
        for row in self.database.list_videos():
            code = standardize_video_code(row.get('code', ''))
            author = str(row.get('author', '')).strip()
            updated_author = replace_actor_name_in_author_text(author, normalized_old_name, normalized_new_name)
            if code and updated_author != author:
                author_updates.append({
                    'code': code,
                    'author': updated_author,
                })

        return self.database.rename_actor(
            normalized_old_name,
            normalized_new_name,
            author_updates=author_updates,
        )

    def delete_actor(self, actor_name):
        normalized_actor_name = normalize_actor_name(actor_name)
        if not normalized_actor_name:
            raise ValueError('演员名称不能为空')

        actor_names = {
            str(row.get('name', '')).strip()
            for row in self.database.list_actors()
        }
        if normalized_actor_name not in actor_names:
            raise ValueError(f'未找到演员：{normalized_actor_name}')

        return self.database.delete_actor(normalized_actor_name)


def normalize_code_prefix(prefix):
    normalized = str(prefix or '').strip().upper()
    if not normalized:
        return ''
    if not CODE_PREFIX_RE.fullmatch(normalized):
        raise ValueError('番号前缀只能包含英文字母和数字')
    if not any(char.isalpha() for char in normalized):
        raise ValueError('番号前缀至少要包含一个字母')
    return normalized


def replace_code_prefix_in_code(code, old_prefix, new_prefix):
    normalized_code = standardize_video_code(code)
    normalized_old_prefix = str(old_prefix or '').strip().upper()
    normalized_new_prefix = str(new_prefix or '').strip().upper()
    if extract_code_prefix(normalized_code) != normalized_old_prefix:
        return normalized_code
    suffix = normalized_code[len(normalized_old_prefix):].lstrip('-_ ')
    return f'{normalized_new_prefix}-{suffix}' if suffix else normalized_new_prefix


def replace_actor_name_in_author_text(author_text, old_name, new_name):
    normalized_old_name = normalize_actor_name(old_name)
    normalized_new_name = normalize_actor_name(new_name)
    actor_names = split_actor_names(author_text)
    if not actor_names or normalized_old_name not in actor_names:
        return str(author_text or '').strip()

    replaced = []
    seen = set()
    for actor_name in actor_names:
        candidate = normalized_new_name if actor_name == normalized_old_name else actor_name
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        replaced.append(candidate)

    return ' '.join(replaced)

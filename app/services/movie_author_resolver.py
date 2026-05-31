import re

from app.core.video_code import compact_video_code
from app.core.javtxt_video_state import is_javtxt_eligible_movie
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.javtxt_entry_state import (
    JAVTXT_SEARCH_STATE_FAILED,
    JAVTXT_SEARCH_STATE_NO_RESULT,
    JAVTXT_SEARCH_STATE_RESOLVED,
    classify_search_state,
    is_resolved_search_state,
    is_retryable_search_state,
)
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.scraper.javtxt_scraper import JavtxtScraper


class MovieAuthorResolver:
    def __init__(self, database, scraper=None, headless=True, should_stop=None, logger=None):
        self.database = database
        self.logger = logger
        self.scraper = scraper or JavtxtScraper(headless=headless, logger=logger)
        self.should_stop = should_stop or (lambda: False)
        self._author_cache = {}
        self._status_cache = {}

    def session(self):
        return self.scraper.session()

    def enrich_entries(self, entries, progress_callback=None):
        return self.enrich_entries_with_details(entries, progress_callback=progress_callback).get('entries', [])

    def enrich_entries_with_details(self, entries, max_lookup_count=None, progress_callback=None):
        normalized_entries = self._prepare_entries(entries)
        cached_rows = self._load_cached_rows(normalized_entries)
        pending_video_count_before = self.count_pending_entries(normalized_entries, cached_rows=cached_rows)
        requested_lookup_count = pending_video_count_before
        if max_lookup_count is not None:
            requested_lookup_count = min(
                pending_video_count_before,
                max(0, int(max_lookup_count or 0)),
            )
        self._log(
            'INFO',
            '作者解析任务准备完成',
            entry_count=len(normalized_entries),
            pending_video_count_before=pending_video_count_before,
            requested_lookup_count=requested_lookup_count,
            max_lookup_count=max_lookup_count if max_lookup_count is not None else '',
        )

        processed_video_count = 0
        success_video_count = 0
        failed_video_count = 0

        for entry in normalized_entries:
            if processed_video_count >= requested_lookup_count:
                self._log('INFO', '作者解析达到本轮上限', processed_video_count=processed_video_count)
                break
            if self.should_stop():
                self._log('WARNING', '作者解析收到停止请求', processed_video_count=processed_video_count)
                break

            code = self._normalize_code(entry.get('code', ''))
            if not code:
                self._log('WARNING', '条目缺少有效番号，跳过作者解析', raw_code=entry.get('code', ''))
                continue

            should_attempt, skip_reason = self._should_attempt_lookup(entry, cached_rows)
            if not should_attempt:
                self._log('INFO', '跳过作者解析', code=code, reason=skip_reason)
                continue

            resolution = self._resolve_author_result(code, cached_rows.get(code, {}))
            processed_video_count += 1

            author = normalize_second_source_actor_text(resolution.get('author', ''))
            status = resolution.get('status', UNENRICHED_STATUS)
            author_raw = str(resolution.get('author_raw', '') or '').strip()
            javtxt_tags = str(resolution.get('javtxt_tags', '') or '').strip()
            entry['javtxt_enrichment_status'] = status
            entry['javtxt_movie_id'] = str(resolution.get('javtxt_movie_id', '') or '').strip()
            entry['javtxt_url'] = str(resolution.get('javtxt_url', '') or '').strip()
            entry['javtxt_tags'] = javtxt_tags
            entry['author_raw'] = author_raw
            if author:
                entry['author'] = author
            if status == ENRICHED_STATUS:
                success_video_count += 1
            elif status == FAILED_STATUS:
                failed_video_count += 1

            self._log(
                'INFO',
                '作者解析完成',
                code=code,
                status=status,
                author=author,
                processed_video_count=processed_video_count,
                success_video_count=success_video_count,
                failed_video_count=failed_video_count,
            )

            if progress_callback is not None:
                progress_callback(
                    {
                        'code': code,
                        'author': author,
                        'status': status,
                        'processed_video_count': processed_video_count,
                        'success_video_count': success_video_count,
                        'failed_video_count': failed_video_count,
                    }
                )

            cached_rows[code] = {
                'code': code,
                'javtxt_actors': author,
                'javtxt_actors_raw': author_raw,
                'javtxt_enrichment_status': status,
                'javtxt_movie_id': entry.get('javtxt_movie_id', ''),
                'javtxt_url': entry.get('javtxt_url', ''),
                'javtxt_tags': javtxt_tags,
            }

        pending_video_count_after = self.count_pending_entries(normalized_entries, cached_rows=cached_rows)
        self._log(
            'INFO',
            '作者解析任务结束',
            processed_video_count=processed_video_count,
            success_video_count=success_video_count,
            failed_video_count=failed_video_count,
            pending_video_count_after=pending_video_count_after,
        )
        return {
            'entries': normalized_entries,
            'processed_video_count': processed_video_count,
            'success_video_count': success_video_count,
            'failed_video_count': failed_video_count,
            'pending_video_count': pending_video_count_after,
            'requested_video_count': requested_lookup_count,
            'completed': pending_video_count_after <= 0,
        }

    def count_pending_entries(self, entries, cached_rows=None):
        normalized_entries = self._prepare_entries(entries)
        cached_rows = cached_rows if cached_rows is not None else self._load_cached_rows(normalized_entries)
        pending_count = 0
        for entry in normalized_entries:
            should_attempt, _ = self._should_attempt_lookup(entry, cached_rows)
            if should_attempt:
                pending_count += 1
        return pending_count

    def _normalize_entry(self, entry):
        updated = dict(entry or {})
        updated['author'] = normalize_second_source_actor_text(updated.get('author', ''))
        updated['author_raw'] = str(updated.get('author_raw', updated.get('author', '')) or '').strip()
        return updated

    def _prepare_entries(self, entries):
        normalized_entries = [self._normalize_entry(entry) for entry in (entries or [])]
        normalized_entries.sort(key=self._lookup_order_key)
        return normalized_entries

    def _load_cached_rows(self, entries):
        eligible_codes = [
            self._normalize_code(entry.get('code', ''))
            for entry in entries
            if self._should_lookup_author(entry)
        ]
        cached_rows = self.database.get_javtxt_actor_cache_by_codes(eligible_codes)
        self._log(
            'INFO',
            '已加载作者缓存',
            eligible_code_count=len(eligible_codes),
            cached_row_count=len(cached_rows),
        )
        return cached_rows

    def _should_attempt_lookup(self, entry, cached_rows):
        if not self._should_lookup_author(entry):
            return False, 'not_eligible_for_javtxt_lookup'

        code = self._normalize_code(entry.get('code', ''))
        if not code:
            return False, 'invalid_code'

        entry_search_state = classify_search_state(entry, cached_row=entry)
        if is_resolved_search_state(entry_search_state):
            return False, f'entry_terminal_state:{entry_search_state}'
        if self._has_author(entry):
            return False, 'author_already_present'

        cached_row = cached_rows.get(code, {})
        cached_search_state = classify_search_state(cached_row, cached_row=cached_row)
        cached_author = normalize_second_source_actor_text((cached_row or {}).get('javtxt_actors', ''))
        if cached_author:
            entry['author'] = cached_author
            return False, 'cached_author_applied'
        if is_resolved_search_state(cached_search_state):
            entry['author_raw'] = str((cached_row or {}).get('javtxt_actors_raw', '') or '').strip()
            return False, f'cached_terminal_state:{cached_search_state}'
        if is_retryable_search_state(cached_search_state):
            return True, f'cached_{cached_search_state}'
        return False, f'cached_unknown_state:{cached_search_state}'

    @staticmethod
    def _has_author(entry):
        return bool(normalize_second_source_actor_text((entry or {}).get('author', '')))

    def _resolve_author_result(self, code, cached_row):
        if code in self._author_cache or code in self._status_cache:
            self._log(
                'INFO',
                '命中进程内作者缓存',
                code=code,
                status=self._status_cache.get(code, UNENRICHED_STATUS),
                author=self._author_cache.get(code, ''),
            )
            return {
                'author': self._author_cache.get(code, ''),
                'status': self._status_cache.get(code, UNENRICHED_STATUS),
                'author_raw': str((cached_row or {}).get('javtxt_actors_raw', '') or '').strip(),
                'javtxt_movie_id': str((cached_row or {}).get('javtxt_movie_id', '') or '').strip(),
                'javtxt_url': str((cached_row or {}).get('javtxt_url', '') or '').strip(),
                'javtxt_tags': str((cached_row or {}).get('javtxt_tags', '') or '').strip(),
            }

        cached_author = normalize_second_source_actor_text((cached_row or {}).get('javtxt_actors', ''))
        cached_status = self._normalize_video_status((cached_row or {}).get('javtxt_enrichment_status', ''))
        cached_search_state = classify_search_state(cached_row, cached_row=cached_row)
        if cached_author:
            self._author_cache[code] = cached_author
            resolved_status = self._status_from_search_state(cached_search_state, ENRICHED_STATUS)
            self._status_cache[code] = resolved_status
            self._log('INFO', '命中数据库作者缓存', code=code, status=ENRICHED_STATUS, author=cached_author)
            return {
                'author': cached_author,
                'status': resolved_status,
                'author_raw': str((cached_row or {}).get('javtxt_actors_raw', cached_author) or '').strip(),
                'javtxt_movie_id': str((cached_row or {}).get('javtxt_movie_id', '') or '').strip(),
                'javtxt_url': str((cached_row or {}).get('javtxt_url', '') or '').strip(),
                'javtxt_tags': str((cached_row or {}).get('javtxt_tags', '') or '').strip(),
            }
        if is_resolved_search_state(cached_search_state):
            resolved_status = self._status_from_search_state(cached_search_state, cached_status)
            self._author_cache[code] = ''
            self._status_cache[code] = resolved_status
            self._log('INFO', '命中数据库终态缓存，不再请求详情页', code=code, status=cached_status)
            return {
                'author': '',
                'status': resolved_status,
                'author_raw': str((cached_row or {}).get('javtxt_actors_raw', '') or '').strip(),
                'javtxt_movie_id': str((cached_row or {}).get('javtxt_movie_id', '') or '').strip(),
                'javtxt_url': str((cached_row or {}).get('javtxt_url', '') or '').strip(),
                'javtxt_tags': str((cached_row or {}).get('javtxt_tags', '') or '').strip(),
            }

        author = ''
        status = UNENRICHED_STATUS
        error_message = ''
        info = {}
        try:
            self._log('INFO', '开始请求 JAVTXT 详情页', code=code)
            info = self.scraper.fetch_by_code(code)
            if info.get('found'):
                author = normalize_second_source_actor_text(info.get('author', ''))
                if author and not str(info.get('javtxt_actors', '') or '').strip():
                    info = dict(info)
                    info['javtxt_actors'] = author
                status = ENRICHED_STATUS
                if not author:
                    error_message = 'JAVTXT 未返回演员信息'
            else:
                status = NO_SEARCH_RESULTS_STATUS
                error_message = str(info.get('error', '') or 'JAVTXT 未找到匹配结果')
        except Exception as exc:
            status = FAILED_STATUS
            error_message = str(exc)

        self._author_cache[code] = author
        self._status_cache[code] = status
        self._save_video_cache(code, info, status=status, error=error_message)
        self._log(
            'INFO',
            'JAVTXT 请求结果已写入缓存',
            code=code,
            status=status,
            author=author,
            error=error_message,
        )
        return {
            'author': author,
            'author_raw': str((info or {}).get('author_raw', (info or {}).get('javtxt_actors_raw', author)) or '').strip(),
            'status': status,
            'javtxt_movie_id': str((info or {}).get('javtxt_movie_id', '') or '').strip(),
            'javtxt_url': str((info or {}).get('javtxt_url', '') or '').strip(),
            'javtxt_tags': str((info or {}).get('javtxt_tags', '') or '').strip(),
        }

    def _save_video_cache(self, code, info, status=ENRICHED_STATUS, error=''):
        if self.database is None or not hasattr(self.database, 'save_javtxt_cache_for_video'):
            self._log('WARNING', '数据库未提供 JAVTXT 缓存写入接口，跳过缓存落库', code=code)
            return
        try:
            self.database.save_javtxt_cache_for_video(
                code,
                info,
                status=status,
                error=error,
            )
        except Exception as exc:
            self._log('ERROR', '写入 JAVTXT 视频缓存失败', code=code, status=status, error=str(exc))
            return
        self._log('INFO', 'JAVTXT 视频缓存写入完成', code=code, status=status, error=error)

    def _should_lookup_author(self, entry):
        return is_javtxt_eligible_movie(entry)

    @staticmethod
    def _normalize_code(value):
        return compact_video_code(value)

    @staticmethod
    def _normalize_video_status(value):
        text = str(value or '').strip()
        return text or UNENRICHED_STATUS

    @staticmethod
    def _status_from_search_state(search_state, fallback_status=UNENRICHED_STATUS):
        if search_state == JAVTXT_SEARCH_STATE_RESOLVED:
            return ENRICHED_STATUS
        if search_state == JAVTXT_SEARCH_STATE_NO_RESULT:
            return NO_SEARCH_RESULTS_STATUS
        if search_state == JAVTXT_SEARCH_STATE_FAILED:
            return FAILED_STATUS
        return fallback_status

    def _lookup_order_key(self, entry):
        normalized_code = self._normalize_code((entry or {}).get('code', ''))
        prefix_part = re.match(r'[A-Z]+', normalized_code or '')
        number_match = re.search(r'(\d+)', normalized_code or '')
        prefix_text = prefix_part.group(0) if prefix_part else normalized_code
        number_value = int(number_match.group(1)) if number_match else 10 ** 12
        return (prefix_text, number_value, normalized_code)

    def _log(self, level, message, **fields):
        if self.logger is not None:
            self.logger.log(level, message, service='movie_author_resolver', **fields)

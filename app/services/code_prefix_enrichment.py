from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.scraper.avfan_code_prefix_scraper import AvfanCodePrefixScraper
from app.scraper.exceptions import HumanVerificationRequiredError
from app.services.code_prefix_entry_parser import parse_code_prefix_card
from app.services.code_prefix_library import CodePrefixLibrary, extract_code_prefix
from app.services.movie_author_resolver import MovieAuthorResolver


class CodePrefixEnrichmentService:
    def __init__(self, database, scraper=None, show_browser=False, should_stop=None, progress_tracker=None):
        self.database = database
        self.prefix_library = CodePrefixLibrary(database)
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.scraper = scraper or AvfanCodePrefixScraper(headless=not show_browser)
        self.author_resolver = MovieAuthorResolver(
            database,
            headless=not show_browser,
            should_stop=self.should_stop,
        )

    def enrich_next_prefixes(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        candidates = self._candidate_prefixes(limit)
        results = []
        success_count = 0
        failed_count = 0
        stopped = False

        if self.progress_tracker is not None:
            self.progress_tracker.start('番号库', len(candidates), source_label='天陨阁')

        for prefix in candidates:
            if self.should_stop():
                stopped = True
                break

            try:
                with self.scraper.session() as page:
                    collected = self._collect_single_prefix(page, prefix)
                result = self._finalize_single_prefix(prefix, collected)
                results.append(result)
                if result.get('stopped'):
                    stopped = True
                    self._update_progress(len(results), success_count, failed_count + 1, prefix)
                    break
                if result.get('status') == ENRICHED_STATUS:
                    success_count += 1
                else:
                    failed_count += 1
            except HumanVerificationRequiredError as exc:
                error_message = str(exc)
                self.database.save_code_prefix_enrichment(
                    prefix=prefix,
                    status=FAILED_STATUS,
                    total_pages=0,
                    total_videos=0,
                    error=error_message,
                )
                results.append({
                    'prefix': prefix,
                    'status': FAILED_STATUS,
                    'error': error_message,
                })
                failed_count += 1
                self._update_progress(len(results), success_count, failed_count, prefix)
                result = {
                    'requested': limit,
                    'processed_count': len(results),
                    'success_count': success_count,
                    'failed_count': failed_count,
                    'remaining_count': self._remaining_prefix_count(),
                    'results': results,
                    'stopped': True,
                    'requires_manual_verification': True,
                    'message': error_message,
                    'entity_label': '番号',
                    'remaining_label': '剩余未补全番号',
                }
                self._finish_progress(error_message, stopped=True)
                return result
            except Exception as exc:
                error_message = str(exc)
                self.database.save_code_prefix_enrichment(
                    prefix=prefix,
                    status=FAILED_STATUS,
                    total_pages=0,
                    total_videos=0,
                    error=error_message,
                )
                results.append({
                    'prefix': prefix,
                    'status': FAILED_STATUS,
                    'error': error_message,
                })
                failed_count += 1

            self._update_progress(len(results), success_count, failed_count, prefix)

        result = {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': self._remaining_prefix_count(),
            'results': results,
            'stopped': stopped,
            'entity_label': '番号',
            'remaining_label': '剩余未补全番号',
        }
        self._finish_progress('番号补全已完成。' if not stopped else '番号补全已停止。', stopped=stopped)
        return result

    def _update_progress(self, processed_count, success_count, failed_count, current_item):
        if self.progress_tracker is not None:
            self.progress_tracker.update(
                processed_count=processed_count,
                success_count=success_count,
                failed_count=failed_count,
                current_item=current_item,
            )

    def _finish_progress(self, message, stopped=False):
        if self.progress_tracker is not None:
            self.progress_tracker.finish(message=message, stopped=stopped)

    def _candidate_prefixes(self, limit):
        records = self.database.list_code_prefix_enrichment_records()
        prefixes = []
        for row in self.prefix_library.list_prefixes():
            prefix = row.get('prefix', '')
            status = records.get(prefix, {}).get('enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS):
                prefixes.append(prefix)
            if len(prefixes) >= limit:
                break
        return prefixes

    def _remaining_prefix_count(self):
        records = self.database.list_code_prefix_enrichment_records()
        remaining = 0
        for row in self.prefix_library.list_prefixes():
            prefix = row.get('prefix', '')
            status = records.get(prefix, {}).get('enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS):
                remaining += 1
        return remaining

    def _collect_single_prefix(self, page, prefix):
        parsed_entries = []
        self.scraper.open_listing_page(page, prefix, 1)
        total_pages = self.scraper.detect_total_pages(page)
        stopped_early = False

        for page_number in range(1, total_pages + 1):
            if self.should_stop():
                stopped_early = True
                break
            if page_number > 1:
                self.scraper.open_listing_page(page, prefix, page_number)
            parsed_entries.extend(
                self._parse_entries(prefix, self.scraper.collect_page_entries(page), page_number)
            )

        if stopped_early:
            return {
                'prefix': prefix,
                'status': FAILED_STATUS,
                'error': '用户已停止补全',
                'stopped': True,
            }

        unique_entries = self._dedupe_entries(parsed_entries)
        return {
            'prefix': prefix,
            'total_pages': total_pages,
            'entries': unique_entries,
        }

    def _finalize_single_prefix(self, prefix, collected):
        if collected.get('stopped'):
            return collected

        total_pages = int(collected.get('total_pages', 0) or 0)
        unique_entries = list(collected.get('entries', []) or [])
        with self.author_resolver.session():
            unique_entries = self.author_resolver.enrich_entries(unique_entries)
        if unique_entries:
            self.database.replace_code_prefix_movies(prefix, unique_entries)
            self.database.save_code_prefix_enrichment(
                prefix=prefix,
                status=ENRICHED_STATUS,
                total_pages=total_pages,
                total_videos=len(unique_entries),
                error='',
            )
            return {
                'prefix': prefix,
                'status': ENRICHED_STATUS,
                'total_pages': total_pages,
                'video_count': len(unique_entries),
            }

        self.database.replace_code_prefix_movies(prefix, [])
        self.database.save_code_prefix_enrichment(
            prefix=prefix,
            status=NO_SEARCH_RESULTS_STATUS,
            total_pages=total_pages,
            total_videos=0,
            error='未搜索到番号页面内容',
        )
        return {
            'prefix': prefix,
            'status': NO_SEARCH_RESULTS_STATUS,
            'total_pages': total_pages,
            'video_count': 0,
            'error': '未搜索到番号页面内容',
        }

    def _parse_entries(self, prefix, rows, page_number):
        prefix_upper = str(prefix or '').strip().upper()
        parsed = []
        for row in rows:
            card = parse_code_prefix_card(
                text=row.get('text', ''),
                href=row.get('href', ''),
                prefix=prefix_upper,
                page_number=page_number,
            )
            code = card.get('code', '')
            if not code:
                continue
            if extract_code_prefix(code) != prefix_upper:
                continue
            parsed.append(card)
        return parsed

    @staticmethod
    def _dedupe_entries(entries):
        deduped = {}
        for entry in entries:
            code = entry.get('code', '')
            if not code:
                continue
            deduped[code] = entry
        return [deduped[key] for key in sorted(deduped)]

from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.services.code_prefix_library import CodePrefixLibrary
from app.services.movie_author_resolver import MovieAuthorResolver


class CodePrefixJavtxtEnrichmentService:
    def __init__(self, database, show_browser=False, should_stop=None, progress_tracker=None):
        self.database = database
        self.prefix_library = CodePrefixLibrary(database)
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.author_resolver = MovieAuthorResolver(
            database,
            headless=not show_browser,
            should_stop=self.should_stop,
        )

    def enrich_next_prefixes(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        ready_prefixes = self._ready_prefixes()
        blocked_count = self._blocked_prefix_count()
        remaining_video_count_before = self._remaining_prefix_video_count(ready_prefixes)
        target_video_count = min(limit, remaining_video_count_before)
        results = []
        processed_video_count = 0
        success_video_count = 0
        failed_video_count = 0
        stopped = False
        source_label = get_video_enrichment_source_label(JAVTXT_VIDEO_SOURCE)

        if self.progress_tracker is not None:
            self.progress_tracker.start(
                '番号库',
                target_video_count,
                source_label=source_label,
                count_unit='视频',
            )

        for prefix in ready_prefixes:
            if self.should_stop():
                stopped = True
                break
            remaining_slots = limit - processed_video_count
            if remaining_slots <= 0:
                break

            try:
                result = self._enrich_single_prefix(prefix, remaining_slots)
                results.append(result)
                processed_video_count += int(result.get('processed_video_count', 0) or 0)
                success_video_count += int(result.get('success_video_count', 0) or 0)
                failed_video_count += int(result.get('failed_video_count', 0) or 0)
            except Exception as exc:
                error_message = str(exc)
                self.database.save_code_prefix_enrichment(
                    prefix=prefix,
                    status=FAILED_STATUS,
                    total_pages=0,
                    total_videos=0,
                    error=error_message,
                    source_key=JAVTXT_VIDEO_SOURCE,
                )
                results.append({
                    'prefix': prefix,
                    'status': FAILED_STATUS,
                    'error': error_message,
                    'processed_video_count': 0,
                    'success_video_count': 0,
                    'failed_video_count': 1,
                    'remaining_video_count': self._pending_prefix_video_count(prefix),
                    'count_unit': '视频',
                })
                failed_video_count += 1

            self._update_progress(
                processed_video_count,
                success_video_count,
                failed_video_count,
                prefix,
            )

        message = ''
        if not ready_prefixes and blocked_count > 0:
            message = f'当前有 {blocked_count} 个番号尚未完成天限阁补全，暂时不能使用辛聚谷继续补全。'

        result = {
            'requested': limit,
            'processed_count': processed_video_count,
            'success_count': success_video_count,
            'failed_count': failed_video_count,
            'remaining_count': self._remaining_prefix_video_count(),
            'results': results,
            'stopped': stopped,
            'entity_label': '番号库 / 辛聚谷',
            'source_key': JAVTXT_VIDEO_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余待补全视频',
            'message': message,
            'blocked_count': blocked_count,
            'count_unit': '视频',
        }
        finish_message = message or ('番号库辛聚谷补全已完成。' if not stopped else '番号库辛聚谷补全已停止。')
        self._finish_progress(finish_message, stopped=stopped)
        return result

    def _ready_prefixes(self):
        records = self.database.list_code_prefix_enrichment_records()
        prefixes = []
        for row in self.prefix_library.list_prefixes():
            prefix = row.get('prefix', '')
            record = records.get(prefix, {})
            status = record.get('javtxt_enrichment_status', UNENRICHED_STATUS)
            if status not in (UNENRICHED_STATUS, FAILED_STATUS) or not self._is_ready_for_javtxt(record):
                continue

            movies = self.database.list_code_prefix_movies(prefix)
            pending_count = self.author_resolver.count_pending_entries(movies)
            if pending_count <= 0:
                continue

            prefixes.append(prefix)
        return prefixes

    def _remaining_prefix_video_count(self, prefixes=None):
        target_prefixes = prefixes if prefixes is not None else self._ready_prefixes()
        return sum(self._pending_prefix_video_count(prefix) for prefix in target_prefixes)

    def _pending_prefix_video_count(self, prefix):
        movies = self.database.list_code_prefix_movies(prefix)
        return self.author_resolver.count_pending_entries(movies)

    def _blocked_prefix_count(self):
        records = self.database.list_code_prefix_enrichment_records()
        blocked = 0
        for row in self.prefix_library.list_prefixes():
            prefix = row.get('prefix', '')
            record = records.get(prefix, {})
            status = record.get('javtxt_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS) and not self._is_ready_for_javtxt(record):
                blocked += 1
        return blocked

    @staticmethod
    def _is_ready_for_javtxt(record):
        avfan_status = str((record or {}).get('avfan_enrichment_status', '') or '').strip()
        avfan_total_videos = int((record or {}).get('avfan_total_videos', 0) or 0)
        return avfan_status == ENRICHED_STATUS and avfan_total_videos > 0

    def _enrich_single_prefix(self, prefix, max_video_count):
        movies = self.database.list_code_prefix_movies(prefix)
        if not movies:
            raise RuntimeError('请先使用天限阁补全番号库作品列表。')

        with self.author_resolver.session():
            resolution = self.author_resolver.enrich_entries_with_details(
                movies,
                max_lookup_count=max_video_count,
            )

        enriched_movies = resolution.get('entries', [])
        self.database.replace_code_prefix_movies(prefix, enriched_movies)
        self.database.save_code_prefix_enrichment(
            prefix=prefix,
            status=ENRICHED_STATUS if resolution.get('completed') else UNENRICHED_STATUS,
            total_pages=0,
            total_videos=len(enriched_movies),
            error='',
            source_key=JAVTXT_VIDEO_SOURCE,
        )
        return {
            'prefix': prefix,
            'status': ENRICHED_STATUS if resolution.get('completed') else UNENRICHED_STATUS,
            'video_count': len(enriched_movies),
            'processed_video_count': int(resolution.get('processed_video_count', 0) or 0),
            'success_video_count': int(resolution.get('success_video_count', 0) or 0),
            'failed_video_count': int(resolution.get('failed_video_count', 0) or 0),
            'remaining_video_count': int(resolution.get('pending_video_count', 0) or 0),
            'count_unit': '视频',
        }

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

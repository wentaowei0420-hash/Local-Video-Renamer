from app.core.enrichment_sources import JAVTXT_VIDEO_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, UNENRICHED_STATUS
from app.services.movie_author_resolver import MovieAuthorResolver


class ActorJavtxtEnrichmentService:
    def __init__(self, database, show_browser=False, should_stop=None, progress_tracker=None):
        self.database = database
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.author_resolver = MovieAuthorResolver(
            database,
            headless=not show_browser,
            should_stop=self.should_stop,
        )

    def enrich_next_actors(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        ready_actor_names = self._ready_actor_names()
        blocked_count = self._blocked_actor_count()
        remaining_video_count_before = self._remaining_actor_video_count(ready_actor_names)
        target_video_count = min(limit, remaining_video_count_before)
        results = []
        processed_video_count = 0
        success_video_count = 0
        failed_video_count = 0
        stopped = False
        source_label = get_video_enrichment_source_label(JAVTXT_VIDEO_SOURCE)

        if self.progress_tracker is not None:
            self.progress_tracker.start(
                '演员库',
                target_video_count,
                source_label=source_label,
                count_unit='视频',
            )

        for actor_name in ready_actor_names:
            if self.should_stop():
                stopped = True
                break
            remaining_slots = limit - processed_video_count
            if remaining_slots <= 0:
                break

            try:
                result = self._enrich_single_actor(actor_name, remaining_slots)
                results.append(result)
                processed_video_count += int(result.get('processed_video_count', 0) or 0)
                success_video_count += int(result.get('success_video_count', 0) or 0)
                failed_video_count += int(result.get('failed_video_count', 0) or 0)
            except Exception as exc:
                error_message = str(exc)
                self.database.save_actor_enrichment(
                    actor_name=actor_name,
                    status=FAILED_STATUS,
                    total_pages=0,
                    total_videos=0,
                    error=error_message,
                    actor_id='',
                    source_key=JAVTXT_VIDEO_SOURCE,
                )
                results.append({
                    'actor_name': actor_name,
                    'status': FAILED_STATUS,
                    'error': error_message,
                    'processed_video_count': 0,
                    'success_video_count': 0,
                    'failed_video_count': 1,
                    'remaining_video_count': self._pending_actor_video_count(actor_name),
                    'count_unit': '视频',
                })
                failed_video_count += 1

            current_item = actor_name
            self._update_progress(
                processed_video_count,
                success_video_count,
                failed_video_count,
                current_item,
            )

        message = ''
        if not ready_actor_names and blocked_count > 0:
            message = f'当前有 {blocked_count} 个演员尚未完成天限阁补全，暂时不能使用辛聚谷继续补全。'

        result = {
            'requested': limit,
            'processed_count': processed_video_count,
            'success_count': success_video_count,
            'failed_count': failed_video_count,
            'remaining_count': self._remaining_actor_video_count(),
            'results': results,
            'stopped': stopped,
            'entity_label': '演员库 / 辛聚谷',
            'source_key': JAVTXT_VIDEO_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余待补全视频',
            'message': message,
            'blocked_count': blocked_count,
            'count_unit': '视频',
        }
        finish_message = message or ('演员库辛聚谷补全已完成。' if not stopped else '演员库辛聚谷补全已停止。')
        self._finish_progress(finish_message, stopped=stopped)
        return result

    def _ready_actor_names(self):
        records = self.database.list_actor_enrichment_records()
        actor_names = []
        for row in self.database.list_actors():
            actor_name = str(row.get('name', '')).strip()
            if not actor_name:
                continue
            record = records.get(actor_name, {})
            status = record.get('javtxt_enrichment_status', UNENRICHED_STATUS)
            if status not in (UNENRICHED_STATUS, FAILED_STATUS) or not self._is_ready_for_javtxt(record):
                continue

            movies = self.database.list_actor_movies(actor_name)
            pending_count = self.author_resolver.count_pending_entries(movies)
            if pending_count <= 0:
                continue

            actor_names.append(actor_name)
        return actor_names

    def _remaining_actor_video_count(self, ready_actor_names=None):
        actor_names = ready_actor_names if ready_actor_names is not None else self._ready_actor_names()
        return sum(self._pending_actor_video_count(actor_name) for actor_name in actor_names)

    def _pending_actor_video_count(self, actor_name):
        movies = self.database.list_actor_movies(actor_name)
        return self.author_resolver.count_pending_entries(movies)

    def _blocked_actor_count(self):
        records = self.database.list_actor_enrichment_records()
        blocked = 0
        for row in self.database.list_actors():
            actor_name = str(row.get('name', '')).strip()
            if not actor_name:
                continue
            record = records.get(actor_name, {})
            status = record.get('javtxt_enrichment_status', UNENRICHED_STATUS)
            if status in (UNENRICHED_STATUS, FAILED_STATUS) and not self._is_ready_for_javtxt(record):
                blocked += 1
        return blocked

    @staticmethod
    def _is_ready_for_javtxt(record):
        avfan_status = str((record or {}).get('avfan_enrichment_status', '') or '').strip()
        avfan_total_videos = int((record or {}).get('avfan_total_videos', 0) or 0)
        return avfan_status == ENRICHED_STATUS and avfan_total_videos > 0

    def _enrich_single_actor(self, actor_name, max_video_count):
        movies = self.database.list_actor_movies(actor_name)
        if not movies:
            raise RuntimeError('请先使用天限阁补全演员库作品列表。')

        with self.author_resolver.session():
            resolution = self.author_resolver.enrich_entries_with_details(
                movies,
                max_lookup_count=max_video_count,
            )

        enriched_movies = resolution.get('entries', [])
        self.database.replace_actor_movies(actor_name, enriched_movies)
        self.database.save_actor_enrichment(
            actor_name=actor_name,
            status=ENRICHED_STATUS if resolution.get('completed') else UNENRICHED_STATUS,
            total_pages=0,
            total_videos=len(enriched_movies),
            error='',
            actor_id='',
            source_key=JAVTXT_VIDEO_SOURCE,
        )
        return {
            'actor_name': actor_name,
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

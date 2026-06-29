from app.core.enrichment_sources import BAOMU_ACTOR_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.core.enrichment_targets import ACTOR_BIRTHDAY_TARGET
from app.scraper.baomu_actor_scraper import BaomuActorScraper
from app.services.enrichment import start_progress_tracker
from app.services.library.canglangge_candidate_service import CanglanggeCandidateService


class ActorBaomuEnrichmentService:
    REQUIRED_FIELDS = ('birthday', 'height', 'bust', 'waist', 'hip')

    def __init__(
        self,
        database,
        scraper=None,
        candidate_service=None,
        show_browser=False,
        should_stop=None,
        progress_tracker=None,
        logger=None,
    ):
        self.database = database
        self.scraper = scraper or BaomuActorScraper(headless=not show_browser)
        self.canglangge_candidate_service = candidate_service or CanglanggeCandidateService(database)
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.logger = logger

    def enrich_next_actors(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        candidates = self._candidate_actors()
        target_candidates = candidates[:limit]
        results = []
        success_count = 0
        failed_count = 0
        stopped = False
        source_label = get_video_enrichment_source_label(BAOMU_ACTOR_SOURCE)

        if self.progress_tracker is not None:
            start_progress_tracker(
                self.progress_tracker,
                '演员生日',
                len(target_candidates),
                source_label=source_label,
                count_unit='演员',
                target_type=ACTOR_BIRTHDAY_TARGET,
                source_key=BAOMU_ACTOR_SOURCE,
                log_path=str(getattr(self.logger, 'log_path', '') or ''),
                task_kind='single',
            )

        with self.scraper.session() as page:
            for candidate in target_candidates:
                actor_name = candidate['actor_name']
                if self.should_stop():
                    stopped = True
                    break
                try:
                    result = self._enrich_single_actor(page, actor_name)
                except Exception as exc:
                    error_message = str(exc)
                    self.database.save_baomu_actor_profile(actor_name, FAILED_STATUS, error=error_message)
                    result = {'actor_name': actor_name, 'status': FAILED_STATUS, 'error': error_message}
                    failed_count += 1
                else:
                    if result.get('status') == ENRICHED_STATUS:
                        success_count += 1
                    else:
                        failed_count += 1
                results.append(result)
                self._update_progress(len(results), success_count, failed_count, actor_name)

        self._finish_progress('保木补全已完成。' if not stopped else '保木补全已停止。', stopped=stopped)
        return {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': self._remaining_actor_count(),
            'results': results,
            'stopped': stopped,
            'entity_label': '演员生日',
            'source_key': BAOMU_ACTOR_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余未补全演员',
        }

    def _candidate_actors(self):
        actor_rows = self.database.list_actors() if hasattr(self.database, 'list_actors') else []
        enrichment_records = self.database.list_actor_enrichment_records()
        candidates = []
        seen = set()

        for row in self.canglangge_candidate_service.list_candidates():
            actor_name = str((row or {}).get('actor_name', '') or '').strip()
            if not actor_name or actor_name in seen:
                continue
            if self._is_candidate(None, enrichment_records.get(actor_name, {})):
                candidates.append({'actor_name': actor_name, 'priority': 1})
                seen.add(actor_name)

        for row in actor_rows:
            actor_name = str((row or {}).get('name', '') or '').strip()
            if not actor_name or actor_name in seen:
                continue
            if self._is_candidate(row, enrichment_records.get(actor_name, {})):
                candidates.append({'actor_name': actor_name, 'priority': 2})
                seen.add(actor_name)

        return sorted(candidates, key=lambda item: (item['priority'], item['actor_name']))

    def _is_candidate(self, actor_row, record):
        current = dict(record or {})
        binghuo_status = str(current.get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
        baomu_status = str(current.get('baomu_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
        if binghuo_status == UNENRICHED_STATUS:
            return False
        if baomu_status != UNENRICHED_STATUS:
            return False
        return not self._is_complete_profile(actor_row, current, include_baomu=False)

    def _remaining_actor_count(self):
        return len(self._candidate_actors())

    def _enrich_single_actor(self, page, actor_name):
        self.scraper.open_actor_page(page, actor_name)
        profile = self.scraper.parse_profile(page)
        if not any(str((profile or {}).get(field_name, '') or '').strip() for field_name in self.REQUIRED_FIELDS):
            self.database.save_baomu_actor_profile(actor_name, NO_SEARCH_RESULTS_STATUS, error='无搜索结果')
            return {'actor_name': actor_name, 'status': NO_SEARCH_RESULTS_STATUS, 'error': '无搜索结果'}

        self.database.save_baomu_actor_profile(
            actor_name,
            ENRICHED_STATUS,
            birthday=str((profile or {}).get('birthday', '') or '').strip(),
            height=str((profile or {}).get('height', '') or '').strip(),
            bust=str((profile or {}).get('bust', '') or '').strip(),
            cup=str((profile or {}).get('cup', '') or '').strip().upper(),
            measurements_raw=str((profile or {}).get('measurements_raw', '') or '').strip(),
            waist=str((profile or {}).get('waist', '') or '').strip(),
            hip=str((profile or {}).get('hip', '') or '').strip(),
        )
        return {
            'actor_name': actor_name,
            'status': ENRICHED_STATUS,
            'birthday': str((profile or {}).get('birthday', '') or '').strip(),
            'height': str((profile or {}).get('height', '') or '').strip(),
            'bust': str((profile or {}).get('bust', '') or '').strip(),
            'cup': str((profile or {}).get('cup', '') or '').strip().upper(),
            'measurements_raw': str((profile or {}).get('measurements_raw', '') or '').strip(),
            'waist': str((profile or {}).get('waist', '') or '').strip(),
            'hip': str((profile or {}).get('hip', '') or '').strip(),
        }

    @classmethod
    def _is_complete_profile(cls, actor_row, record, include_baomu):
        merged = cls._merged_profile(actor_row, record, include_baomu=include_baomu)
        return all(merged.get(field_name) for field_name in cls.REQUIRED_FIELDS)

    @staticmethod
    def _merged_profile(actor_row, record, include_baomu):
        actor_row = dict(actor_row or {})
        record = dict(record or {})
        merged = {
            'birthday': str(actor_row.get('birthday', '') or record.get('binghuo_birthday', '') or '').strip(),
            'height': str(record.get('binghuo_height', '') or '').strip(),
            'bust': str(record.get('binghuo_bust', '') or '').strip(),
            'waist': str(record.get('binghuo_waist', '') or '').strip(),
            'hip': str(record.get('binghuo_hip', '') or '').strip(),
        }
        if include_baomu:
            merged['birthday'] = merged['birthday'] or str(record.get('baomu_birthday', '') or '').strip()
            merged['height'] = merged['height'] or str(record.get('baomu_height', '') or '').strip()
            merged['bust'] = merged['bust'] or str(record.get('baomu_bust', '') or '').strip()
            merged['waist'] = merged['waist'] or str(record.get('baomu_waist', '') or '').strip()
            merged['hip'] = merged['hip'] or str(record.get('baomu_hip', '') or '').strip()
        return merged

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

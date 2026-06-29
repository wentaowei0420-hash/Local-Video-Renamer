import re

from app.core.enrichment_sources import BINGHUO_ACTOR_SOURCE, get_video_enrichment_source_label
from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    NO_VIDEO_DETAIL_STATUS,
    UNENRICHED_STATUS,
)
from app.core.enrichment_targets import ACTOR_BIRTHDAY_TARGET
from app.scraper.binghuo_actor_scraper import BinghuoActorScraper
from app.services.enrichment import start_progress_tracker
from app.services.library.canglangge_candidate_service import CanglanggeCandidateService


EXACT_MATCH_SUFFIX_RE = re.compile(r'\[[^\]]*\]\s*$')
EXACT_MATCH_SPLIT_RE = re.compile(r'[,，/|]')
EXACT_MATCH_PREFIX_RE = re.compile(r'^\s*\d+\.\s*')


class ActorBinghuoEnrichmentService:
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
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.logger = logger
        self.scraper = scraper or BinghuoActorScraper(headless=not show_browser, logger=logger)
        self.canglangge_candidate_service = candidate_service or CanglanggeCandidateService(database)

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
        source_label = get_video_enrichment_source_label(BINGHUO_ACTOR_SOURCE)
        self._log(
            'INFO',
            '演员生日/并火补全任务启动',
            requested_limit=limit,
            candidate_count=len(target_candidates),
            total_candidate_count=len(candidates),
            candidate_names=' | '.join(item['actor_name'] for item in target_candidates[:20]),
        )

        if self.progress_tracker is not None:
            start_progress_tracker(
                self.progress_tracker,
                '演员生日',
                len(target_candidates),
                source_label=source_label,
                count_unit='演员',
                target_type=ACTOR_BIRTHDAY_TARGET,
                source_key=BINGHUO_ACTOR_SOURCE,
                log_path=str(getattr(self.logger, 'log_path', '') or ''),
                task_kind='single',
            )

        with self.scraper.session() as page:
            for candidate in target_candidates:
                actor_name = candidate['actor_name']
                if self.should_stop():
                    stopped = True
                    self._log('WARNING', '演员生日/并火补全收到停止请求', processed_count=len(results))
                    break
                try:
                    result = self._enrich_single_actor(page, actor_name)
                except Exception as exc:
                    error_message = str(exc)
                    self.database.save_binghuo_actor_profile(
                        actor_name,
                        FAILED_STATUS,
                        person_id=self.database.get_actor_enrichment_record(actor_name).get('binghuo_person_id', ''),
                        error=error_message,
                    )
                    result = {
                        'actor_name': actor_name,
                        'status': FAILED_STATUS,
                        'error': error_message,
                    }
                    failed_count += 1
                    self._log('ERROR', '并火补全失败', actor_name=actor_name, error=error_message)
                else:
                    if result.get('status') == ENRICHED_STATUS:
                        success_count += 1
                    else:
                        failed_count += 1
                self._log_actor_result(actor_name, result)
                results.append(result)
                self._update_progress(len(results), success_count, failed_count, actor_name)

        remaining_count = self._remaining_actor_count()
        result = {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': remaining_count,
            'results': results,
            'stopped': stopped,
            'entity_label': '演员生日',
            'source_key': BINGHUO_ACTOR_SOURCE,
            'source_label': source_label,
            'remaining_label': '剩余未补全演员',
        }
        finish_message = '演员生日/并火补全已完成。' if not stopped else '演员生日/并火补全已停止。'
        self._finish_progress(finish_message, stopped=stopped)
        self._log(
            'INFO',
            '演员生日/并火补全任务结束',
            processed_count=result['processed_count'],
            success_count=result['success_count'],
            failed_count=result['failed_count'],
            remaining_count=result['remaining_count'],
            stopped=stopped,
        )
        return result

    def _candidate_actors(self):
        actor_rows = self.database.list_actors() if hasattr(self.database, 'list_actors') else []
        enrichment_records = self.database.list_actor_enrichment_records()
        candidates = []
        seen = set()

        for row in self.canglangge_candidate_service.list_candidates():
            actor_name = str((row or {}).get('actor_name', '') or '').strip()
            if not actor_name or actor_name in seen:
                continue
            record = enrichment_records.get(actor_name, {})
            birthday = str((row or {}).get('birthday', '') or record.get('binghuo_birthday', '') or '').strip()
            if not birthday:
                if not self._should_process_missing_birthday(record):
                    continue
                candidates.append({'actor_name': actor_name, 'priority': 1})
                seen.add(actor_name)
                continue

            if self._should_process_profile_only(record, birthday=birthday):
                candidates.append({'actor_name': actor_name, 'priority': 2})
                seen.add(actor_name)

        for row in actor_rows:
            actor_name = str((row or {}).get('name', '') or '').strip()
            if not actor_name or actor_name in seen:
                continue
            record = self._normalize_empty_profile_status(actor_name, row, enrichment_records.get(actor_name, {}))
            birthday = str((row or {}).get('birthday', '') or record.get('binghuo_birthday', '') or '').strip()
            if not birthday:
                if not self._should_process_missing_birthday(record):
                    continue
                candidates.append({'actor_name': actor_name, 'priority': self._missing_birthday_priority(record)})
                seen.add(actor_name)
                continue

            if self._should_process_profile_only(record, birthday=birthday):
                candidates.append({'actor_name': actor_name, 'priority': 4})
                seen.add(actor_name)

        return sorted(candidates, key=lambda item: item['priority'])

    def _remaining_actor_count(self):
        return len(self._candidate_actors())

    @staticmethod
    def _should_process_missing_birthday(record):
        status = str((record or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
        if status in (NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS):
            return False
        if ActorBinghuoEnrichmentService._is_incomplete_binghuo_profile(record):
            return False
        return True

    @staticmethod
    def _missing_birthday_priority(record):
        person_id = str((record or {}).get('binghuo_person_id', '') or '').strip()
        has_profile_data = any(
            str((record or {}).get(field, '') or '').strip()
            for field in ('binghuo_age', 'binghuo_height', 'binghuo_bust', 'binghuo_waist', 'binghuo_hip')
        )
        return 2 if person_id or has_profile_data else 3

    @staticmethod
    def _should_process_profile_only(record, birthday=''):
        status = str((record or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
        person_id = str((record or {}).get('binghuo_person_id', '') or '').strip()
        normalized_birthday = str(birthday or (record or {}).get('binghuo_birthday', '') or '').strip()
        if status in (NO_SEARCH_RESULTS_STATUS, NO_VIDEO_DETAIL_STATUS):
            return False
        if not person_id:
            return True
        if normalized_birthday and not ActorBinghuoEnrichmentService._has_binghuo_physical_data(record):
            return True
        return not ActorBinghuoEnrichmentService._has_saved_binghuo_profile_data(record)

    def _enrich_single_actor(self, page, actor_name):
        record = self.database.get_actor_enrichment_record(actor_name)
        person_id = str(record.get('binghuo_person_id', '') or '').strip()
        target_result = None

        if person_id:
            current_url = self.scraper.open_person_page(page, person_id=person_id)
        else:
            self.scraper.open_search_page(page, actor_name)
            search_results = self.scraper.collect_search_results(page)
            exact_matches = [row for row in search_results if self._is_exact_match(actor_name, row)]
            if not exact_matches:
                self.database.save_binghuo_actor_profile(
                    actor_name,
                    NO_SEARCH_RESULTS_STATUS,
                    error='无搜索结果',
                )
                return {
                    'actor_name': actor_name,
                    'status': NO_SEARCH_RESULTS_STATUS,
                    'error': '无搜索结果',
                }
            target_result = exact_matches[0]
            current_url = self.scraper.open_person_page(page, url=target_result.get('href', ''))

        profile = self.scraper.parse_profile(page)
        birthday = str((profile or {}).get('birthday', '') or '').strip()
        age = str((profile or {}).get('age', '') or '').strip()
        height = str((profile or {}).get('height', '') or '').strip()
        bust = str((profile or {}).get('bust', '') or '').strip()
        cup = str((profile or {}).get('cup', '') or '').strip().upper()
        measurements_raw = str((profile or {}).get('measurements_raw', '') or '').strip()
        waist = str((profile or {}).get('waist', '') or '').strip()
        hip = str((profile or {}).get('hip', '') or '').strip()
        resolved_person_id = (
            str((profile or {}).get('person_id', '') or '').strip()
            or str((target_result or {}).get('person_id', '') or '').strip()
            or str(person_id or '').strip()
            or self.scraper.extract_person_id(current_url)
        )
        resolved_status = ENRICHED_STATUS if self._is_complete_binghuo_profile(profile) else NO_VIDEO_DETAIL_STATUS
        self.database.save_binghuo_actor_profile(
            actor_name,
            resolved_status,
            person_id=resolved_person_id,
            birthday=birthday,
            age=age,
            height=height,
            bust=bust,
            cup=cup,
            measurements_raw=measurements_raw,
            waist=waist,
            hip=hip,
            error='',
        )
        return {
            'actor_name': actor_name,
            'status': resolved_status,
            'person_id': resolved_person_id,
            'birthday': birthday,
            'age': age,
            'height': height,
            'bust': bust,
            'cup': cup,
            'measurements_raw': measurements_raw,
            'waist': waist,
            'hip': hip,
        }

    @staticmethod
    def _has_binghuo_physical_data(record):
        return any(
            str((record or {}).get(field_name, '') or '').strip()
            for field_name in ('height', 'bust', 'waist', 'hip', 'binghuo_height', 'binghuo_bust', 'binghuo_waist', 'binghuo_hip')
        )

    @staticmethod
    def _has_saved_binghuo_profile_data(record):
        return any(
            str((record or {}).get(field_name, '') or '').strip()
            for field_name in (
                'binghuo_birthday',
                'binghuo_age',
                'binghuo_height',
                'binghuo_bust',
                'binghuo_waist',
                'binghuo_hip',
            )
        )

    def _normalize_empty_profile_status(self, actor_name, actor_row, record):
        actor_birthday = str((actor_row or {}).get('birthday', '') or '').strip()
        current = dict(record or {})
        status = str((current or {}).get('binghuo_enrichment_status', '') or '').strip() or UNENRICHED_STATUS
        if not actor_birthday or status != ENRICHED_STATUS or self._has_saved_binghuo_profile_data(current):
            return current

        person_id = str((current or {}).get('binghuo_person_id', '') or '').strip()
        self.database.save_binghuo_actor_profile(actor_name, UNENRICHED_STATUS, person_id=person_id)
        current['binghuo_enrichment_status'] = UNENRICHED_STATUS
        return current

    @classmethod
    def _is_complete_binghuo_profile(cls, record):
        birthday = str((record or {}).get('birthday', (record or {}).get('binghuo_birthday', '')) or '').strip()
        return bool(birthday) and cls._has_binghuo_physical_data(record)

    @classmethod
    def _is_incomplete_binghuo_profile(cls, record):
        has_any_profile_data = any(
            str((record or {}).get(field_name, '') or '').strip()
            for field_name in (
                'birthday',
                'binghuo_birthday',
                'age',
                'binghuo_age',
                'height',
                'binghuo_height',
                'bust',
                'binghuo_bust',
                'waist',
                'binghuo_waist',
                'hip',
                'binghuo_hip',
            )
        )
        return has_any_profile_data and not cls._is_complete_binghuo_profile(record)

    @classmethod
    def _is_exact_match(cls, actor_name, result):
        normalized_actor_name = str(actor_name or '').strip()
        title = str((result or {}).get('title', '') or '').strip()
        title = EXACT_MATCH_PREFIX_RE.sub('', title)
        title = EXACT_MATCH_SUFFIX_RE.sub('', title)
        if not title:
            return False
        if title == normalized_actor_name:
            return True
        if title.startswith(normalized_actor_name):
            remainder = title[len(normalized_actor_name):].strip()
            if not remainder or remainder[:1] in ',，/|([':
                return True
        segments = [
            segment.strip()
            for segment in EXACT_MATCH_SPLIT_RE.split(title)
            if segment.strip()
        ]
        return normalized_actor_name in segments

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

    def _log(self, level, message, **fields):
        if self.logger is not None:
            self.logger.log(level, message, service='actor_binghuo_enrichment', **fields)

    def _log_actor_result(self, actor_name, result):
        self._log(
            'INFO',
            '演员生日/并火补全结果',
            actor_name=actor_name,
            person_id=str((result or {}).get('person_id', '') or '').strip(),
            birthday_found=bool(str((result or {}).get('birthday', '') or '').strip()),
            status_written=str((result or {}).get('status', '') or '').strip(),
        )

from __future__ import annotations

import time
from threading import Event, Lock, Thread

from app.core.combo_enrichment import get_combo_label, get_combo_tasks, normalize_combo_key
from app.core.project_paths import COMBO_BROWSER_PROFILES_DIR
from app.scraper.avfan_actor_scraper import AvfanActorScraper
from app.scraper.avfan_code_prefix_scraper import AvfanCodePrefixScraper
from app.scraper.avfan_scraper import ensure_avfan_profile_seeded
from app.services.actor_enrichment import ActorEnrichmentService
from app.services.actor_javtxt_enrichment import ActorJavtxtEnrichmentService
from app.services.code_prefix_enrichment import CodePrefixEnrichmentService
from app.services.code_prefix_javtxt_enrichment import CodePrefixJavtxtEnrichmentService


class ComboEnrichmentService:
    def __init__(self, database, combo_progress_service, logger, should_stop=None):
        self.database = database
        self.combo_progress_service = combo_progress_service
        self.logger = logger
        self.external_should_stop = should_stop or (lambda: False)
        self.internal_stop_event = Event()
        self._result_lock = Lock()

    def run(
        self,
        combo_key,
        limit,
        show_browser=False,
        cooldown_before_search=False,
        combo_task_settings=None,
        batch_mode=False,
    ):
        normalized_combo_key = normalize_combo_key(combo_key)
        combo_label = get_combo_label(normalized_combo_key)
        task_definitions = get_combo_tasks(normalized_combo_key)
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('组合任务数量必须大于 0')

        task_run_configs = self._normalize_task_run_configs(
            task_definitions,
            combo_task_settings,
            default_limit=limit,
            default_show_browser=show_browser,
            default_cooldown_before_search=cooldown_before_search,
        )
        effective_limit = max(
            int(task_config.get('limit', 0) or 0)
            for task_config in task_run_configs.values()
        )

        self.combo_progress_service.start(
            normalized_combo_key,
            effective_limit,
            log_path=str(self.logger.log_path),
        )
        if batch_mode:
            self.combo_progress_service.set_message('组合批次计划运行中，子任务会按各自间隔循环执行。')
        self.logger.log(
            'INFO',
            '组合任务开始执行',
            combo_key=normalized_combo_key,
            combo_label=combo_label,
            limit=effective_limit,
            show_browser=bool(show_browser),
            cooldown_before_search=bool(cooldown_before_search),
            batch_mode=bool(batch_mode),
        )

        results_by_task = {}
        worker_threads = []
        for task_definition in task_definitions:
            task_config = dict(task_run_configs.get(task_definition['task_key'], {}))
            target = self._run_subtask_batch_loop if batch_mode else self._run_subtask_once
            worker_thread = Thread(
                target=target,
                args=(task_definition, task_config, results_by_task),
                daemon=True,
            )
            worker_threads.append(worker_thread)
            worker_thread.start()

        for worker_thread in worker_threads:
            worker_thread.join()

        result = self._build_result(
            normalized_combo_key,
            combo_label,
            results_by_task,
            batch_mode=batch_mode,
        )
        finish_message = result.get('message', '') or (
            '组合批次计划已结束。' if batch_mode else '组合任务已完成。'
        )
        self.combo_progress_service.finish(
            message=finish_message,
            stopped=result.get('stopped', False),
        )
        self.logger.log(
            'INFO',
            '组合任务执行结束',
            combo_key=normalized_combo_key,
            processed_count=result['processed_count'],
            success_count=result['success_count'],
            failed_count=result['failed_count'],
            remaining_count=result['remaining_count'],
            stopped=result['stopped'],
            requires_manual_verification=result['requires_manual_verification'],
            batch_mode=bool(batch_mode),
        )
        return result

    def request_stop(self):
        self.internal_stop_event.set()

    def _run_subtask_once(self, task_definition, task_config, results_by_task):
        result = self._execute_subtask(task_definition, task_config)
        with self._result_lock:
            results_by_task[task_definition['task_key']] = dict(result)

    def _run_subtask_batch_loop(self, task_definition, task_config, results_by_task):
        task_key = task_definition['task_key']
        task_label = task_definition['task_label']
        interval_minutes = max(1, int((task_config or {}).get('batch_interval_minutes', 1) or 1))
        interval_seconds = interval_minutes * 60
        batch_index = 0
        aggregated_result = self._build_empty_task_result(task_definition)

        while not self._should_stop():
            batch_index += 1
            self.logger.log(
                'INFO',
                '子任务批次开始',
                task_key=task_key,
                task_label=task_label,
                batch_index=batch_index,
                limit=int((task_config or {}).get('limit', 1) or 1),
                interval_minutes=interval_minutes,
            )
            result = self._execute_subtask(task_definition, task_config)
            aggregated_result = self._merge_task_result(
                task_definition,
                aggregated_result,
                result,
                batch_index,
            )
            with self._result_lock:
                results_by_task[task_key] = dict(aggregated_result)

            if result.get('requires_manual_verification'):
                self.internal_stop_event.set()
                break

            if self._should_stop() or result.get('stopped'):
                break

            self.logger.log(
                'INFO',
                '子任务进入等待下一批',
                task_key=task_key,
                task_label=task_label,
                batch_index=batch_index,
                interval_minutes=interval_minutes,
            )
            for remaining_seconds in range(interval_seconds, 0, -1):
                if self._should_stop():
                    break
                self.combo_progress_service.update_subtask_message(
                    task_key,
                    message=f'下一批倒计时 {self._format_seconds(remaining_seconds)}',
                    is_running=False,
                    current_item='',
                )
                time.sleep(1)
            if self._should_stop():
                break

        final_message = aggregated_result.get('message', '') or ''
        if self._should_stop() and not aggregated_result.get('requires_manual_verification'):
            final_message = final_message or '组合批次计划已停止。'
        self.combo_progress_service.update_subtask_message(
            task_key,
            message=final_message,
            is_running=False,
            current_item='',
        )
        with self._result_lock:
            results_by_task[task_key] = dict(aggregated_result)

    def _execute_subtask(self, task_definition, task_config):
        task_key = task_definition['task_key']
        task_label = task_definition['task_label']
        limit = max(1, int((task_config or {}).get('limit', 1) or 1))
        show_browser = bool((task_config or {}).get('show_browser'))
        cooldown_before_search = bool((task_config or {}).get('cooldown_before_search'))
        tracker = self.combo_progress_service.build_subtask_tracker(task_definition, self.logger)
        self.logger.log(
            'INFO',
            '子任务准备启动',
            task_key=task_key,
            task_label=task_label,
            limit=limit,
            show_browser=show_browser,
            cooldown_before_search=cooldown_before_search,
        )

        try:
            service, run_method = self._build_task_runner(
                task_definition,
                show_browser=show_browser,
                cooldown_before_search=cooldown_before_search,
                progress_tracker=tracker,
            )
            result = run_method(service, limit)
        except Exception as exc:
            error_message = str(exc)
            self.logger.log(
                'ERROR',
                '子任务执行异常',
                task_key=task_key,
                task_label=task_label,
                error=error_message,
            )
            result = {
                'processed_count': 0,
                'success_count': 0,
                'failed_count': 1,
                'remaining_count': 0,
                'stopped': True,
                'requires_manual_verification': False,
                'message': error_message,
                'entity_label': task_label,
                'results': [],
            }
            self.internal_stop_event.set()

        result.setdefault('task_label', task_label)
        result.setdefault('count_unit', task_definition.get('count_unit', '项'))
        self.combo_progress_service.update_subtask_finish(
            task_key,
            message=result.get('message', ''),
            stopped=result.get('stopped', False),
            result=result,
        )
        self.logger.log(
            'INFO',
            '子任务执行完成',
            task_key=task_key,
            task_label=task_label,
            processed_count=result.get('processed_count', 0),
            success_count=result.get('success_count', 0),
            failed_count=result.get('failed_count', 0),
            remaining_count=result.get('remaining_count', 0),
            stopped=result.get('stopped', False),
            requires_manual_verification=result.get('requires_manual_verification', False),
            result_message=result.get('message', ''),
        )
        if result.get('requires_manual_verification'):
            self.internal_stop_event.set()
        return result

    def _build_task_runner(self, task_definition, show_browser, cooldown_before_search, progress_tracker):
        task_key = task_definition['task_key']
        should_stop = self._should_stop

        if task_key == 'code_prefix_avfan':
            scraper = AvfanCodePrefixScraper(
                headless=not show_browser,
                profile_dir=self._build_avfan_profile_dir(task_key),
            )
            service = CodePrefixEnrichmentService(
                self.database,
                scraper=scraper,
                show_browser=show_browser,
                should_stop=should_stop,
                progress_tracker=progress_tracker,
            )
            return service, lambda current_service, current_limit: current_service.enrich_next_prefixes(current_limit)

        if task_key == 'actor_avfan':
            scraper = AvfanActorScraper(
                headless=not show_browser,
                profile_dir=self._build_avfan_profile_dir(task_key),
            )
            service = ActorEnrichmentService(
                self.database,
                scraper=scraper,
                show_browser=show_browser,
                should_stop=should_stop,
                progress_tracker=progress_tracker,
            )
            return service, lambda current_service, current_limit: current_service.enrich_next_actors(current_limit)

        if task_key == 'code_prefix_javtxt':
            service = CodePrefixJavtxtEnrichmentService(
                self.database,
                show_browser=show_browser,
                should_stop=should_stop,
                progress_tracker=progress_tracker,
            )
            return service, lambda current_service, current_limit: current_service.enrich_next_prefixes(current_limit)

        if task_key == 'actor_javtxt':
            service = ActorJavtxtEnrichmentService(
                self.database,
                show_browser=show_browser,
                should_stop=should_stop,
                progress_tracker=progress_tracker,
            )
            return service, lambda current_service, current_limit: current_service.enrich_next_actors(current_limit)

        raise ValueError(f'不支持的组合子任务: {task_key}')

    @staticmethod
    def _normalize_task_run_configs(
        task_definitions,
        combo_task_settings,
        default_limit,
        default_show_browser,
        default_cooldown_before_search,
    ):
        normalized = {}
        raw_settings = dict(combo_task_settings or {})
        for task_definition in task_definitions:
            task_key = task_definition['task_key']
            current_settings = dict(raw_settings.get(task_key, {}) or {})
            normalized[task_key] = {
                'limit': max(1, int(current_settings.get('limit', default_limit) or default_limit)),
                'show_browser': bool(current_settings.get('show_browser', default_show_browser)),
                'cooldown_before_search': bool(
                    current_settings.get('cooldown_before_search', default_cooldown_before_search)
                ),
                'batch_interval_minutes': max(1, int(current_settings.get('batch_interval_minutes', 1) or 1)),
            }
        return normalized

    def _build_avfan_profile_dir(self, task_key):
        profile_dir = COMBO_BROWSER_PROFILES_DIR / task_key
        seed_result = ensure_avfan_profile_seeded(profile_dir)
        self.logger.log(
            'INFO',
            'AVFan 组合任务浏览器配置已准备',
            task_key=task_key,
            profile_dir=seed_result.get('profile_dir', str(profile_dir)),
            source_profile_dir=seed_result.get('source_profile_dir', ''),
            seeded=seed_result.get('seeded', False),
            reason=seed_result.get('reason', ''),
        )
        self._log_avfan_profile_seed_status(task_key, seed_result)
        return profile_dir

    def _log_avfan_profile_seed_status(self, task_key, seed_result):
        inherited = bool(seed_result.get('seeded', False))
        source_profile_dir = seed_result.get('source_profile_dir', '') or '未提供'
        target_profile_dir = seed_result.get('profile_dir', '') or str(COMBO_BROWSER_PROFILES_DIR / task_key)
        reason = str(seed_result.get('reason', '') or '').strip()
        reason_text_map = {
            'copied': '本次已从主 AVFan profile 复制登录态到组合任务 profile。',
            'target_has_login_state': '组合任务 profile 已经带有登录态，因此本次没有再次继承。',
            'source_missing_or_empty': '主 AVFan profile 不存在或没有可继承的登录态。',
            'same_profile': '当前直接使用主 AVFan profile，本次不需要额外继承。',
        }
        reason_text = reason_text_map.get(reason, reason or '未提供')
        status_text = '已继承' if inherited else '未继承'
        self.logger.log_emphasis_block(
            'AVFan 登录态继承摘要',
            level='NOTICE' if inherited else 'WARNING',
            lines=[
                f'子任务: {task_key}',
                f'本次是否继承登录态: {status_text}',
                f'继承来源 profile: {source_profile_dir}',
                f'当前使用 profile: {target_profile_dir}',
                f'说明: {reason_text}',
            ],
        )

    def _should_stop(self):
        return self.internal_stop_event.is_set() or bool(self.external_should_stop())

    @staticmethod
    def _build_empty_task_result(task_definition):
        return {
            'task_label': task_definition['task_label'],
            'entity_label': task_definition['task_label'],
            'count_unit': task_definition.get('count_unit', '项'),
            'processed_count': 0,
            'success_count': 0,
            'failed_count': 0,
            'remaining_count': 0,
            'stopped': False,
            'requires_manual_verification': False,
            'message': '',
            'batch_count': 0,
            'last_batch_processed_count': 0,
            'last_batch_success_count': 0,
            'last_batch_failed_count': 0,
        }

    @staticmethod
    def _merge_task_result(task_definition, aggregated_result, latest_result, batch_index):
        merged = dict(aggregated_result or {})
        latest = dict(latest_result or {})
        merged.update(
            {
                'task_label': latest.get('task_label') or merged.get('task_label') or task_definition['task_label'],
                'entity_label': latest.get('entity_label') or merged.get('entity_label') or task_definition['task_label'],
                'count_unit': latest.get('count_unit') or merged.get('count_unit') or task_definition.get('count_unit', '项'),
                'processed_count': int(merged.get('processed_count', 0) or 0) + int(latest.get('processed_count', 0) or 0),
                'success_count': int(merged.get('success_count', 0) or 0) + int(latest.get('success_count', 0) or 0),
                'failed_count': int(merged.get('failed_count', 0) or 0) + int(latest.get('failed_count', 0) or 0),
                'remaining_count': int(latest.get('remaining_count', merged.get('remaining_count', 0)) or 0),
                'stopped': bool(latest.get('stopped')) or bool(merged.get('stopped')),
                'requires_manual_verification': bool(latest.get('requires_manual_verification'))
                or bool(merged.get('requires_manual_verification')),
                'message': str(latest.get('message', '') or merged.get('message', '') or ''),
                'batch_count': max(batch_index, int(merged.get('batch_count', 0) or 0)),
                'last_batch_processed_count': int(latest.get('processed_count', 0) or 0),
                'last_batch_success_count': int(latest.get('success_count', 0) or 0),
                'last_batch_failed_count': int(latest.get('failed_count', 0) or 0),
            }
        )
        return merged

    @staticmethod
    def _build_result(combo_key, combo_label, results_by_task, batch_mode=False):
        ordered_results = {
            task_definition['task_key']: dict(results_by_task.get(task_definition['task_key'], {}))
            for task_definition in get_combo_tasks(combo_key)
        }
        processed_count = sum(int(result.get('processed_count', 0) or 0) for result in ordered_results.values())
        success_count = sum(int(result.get('success_count', 0) or 0) for result in ordered_results.values())
        failed_count = sum(int(result.get('failed_count', 0) or 0) for result in ordered_results.values())
        remaining_count = sum(int(result.get('remaining_count', 0) or 0) for result in ordered_results.values())
        requires_manual_verification = any(
            bool(result.get('requires_manual_verification'))
            for result in ordered_results.values()
        )
        stopped = any(bool(result.get('stopped')) for result in ordered_results.values()) or batch_mode
        message_segments = [
            str(result.get('message', '') or '').strip()
            for result in ordered_results.values()
            if str(result.get('message', '') or '').strip()
        ]
        message = ' | '.join(message_segments)
        if requires_manual_verification and not message:
            message = '组合任务中检测到 AVFan 人机验证。'
        elif batch_mode and not message:
            message = '组合批次计划已停止。'
        return {
            'task_kind': 'combo',
            'combo_key': combo_key,
            'combo_label': combo_label,
            'entity_label': f'组合任务 / {combo_label}',
            'requested': 0,
            'processed_count': processed_count,
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': remaining_count,
            'stopped': stopped,
            'requires_manual_verification': requires_manual_verification,
            'message': message,
            'subtask_results': ordered_results,
            'results': [],
        }

    @staticmethod
    def _format_seconds(total_seconds):
        total_seconds = max(0, int(total_seconds or 0))
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f'{hours:02d}:{minutes:02d}:{seconds:02d}'
        return f'{minutes:02d}:{seconds:02d}'

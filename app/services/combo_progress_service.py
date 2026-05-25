from __future__ import annotations

from threading import Lock

from app.core.combo_enrichment import get_combo_label, get_combo_tasks, normalize_combo_key


class ComboProgressService:
    def __init__(self):
        self._lock = Lock()
        self._state = self._build_default_state()

    def start(self, combo_key, limit, log_path=''):
        normalized_combo_key = normalize_combo_key(combo_key)
        combo_label = get_combo_label(normalized_combo_key)
        task_definitions = get_combo_tasks(normalized_combo_key)
        with self._lock:
            self._state = self._build_default_state()
            self._state.update(
                {
                    'is_running': True,
                    'task_kind': 'combo',
                    'combo_key': normalized_combo_key,
                    'combo_label': combo_label,
                    'limit_per_task': max(0, int(limit or 0)),
                    'target_label': f'组合任务 / {combo_label}',
                    'message': '组合任务已启动，等待子任务加载候选项。',
                    'log_path': str(log_path or ''),
                    'subtasks': {
                        task_definition['task_key']: self._build_subtask_state(task_definition)
                        for task_definition in task_definitions
                    },
                }
            )
            self._recalculate_totals_locked()

    def build_subtask_tracker(self, task_definition, logger):
        return ComboSubtaskProgressTracker(self, task_definition, logger)

    def set_message(self, message):
        with self._lock:
            self._state['message'] = str(message or '')

    def finish(self, message='', stopped=False):
        with self._lock:
            self._recalculate_totals_locked()
            if (
                self._state.get('total_count', 0) > 0
                and self._state.get('processed_count', 0) >= self._state.get('total_count', 0)
            ):
                self._state['progress_percent'] = 100.0
            self._state.update(
                {
                    'is_running': False,
                    'message': str(message or ''),
                    'stopped': bool(stopped),
                }
            )

    def reset(self):
        with self._lock:
            self._state = self._build_default_state()

    def snapshot(self):
        with self._lock:
            return {
                **self._state,
                'subtasks': {
                    task_key: dict(task_state)
                    for task_key, task_state in self._state.get('subtasks', {}).items()
                },
            }

    def update_subtask_start(self, task_key, total_count, source_label='', message='', count_unit='项'):
        with self._lock:
            subtask = self._state.get('subtasks', {}).get(task_key)
            if subtask is None:
                return
            subtask.update(
                {
                    'is_running': True,
                    'source_label': str(source_label or ''),
                    'total_count': max(0, int(total_count or 0)),
                    'processed_count': 0,
                    'success_count': 0,
                    'failed_count': 0,
                    'remaining_count': 0,
                    'current_item': '',
                    'progress_percent': 0.0,
                    'message': str(message or ''),
                    'stopped': False,
                    'requires_manual_verification': False,
                    'count_unit': str(count_unit or subtask.get('count_unit', '项') or '项'),
                }
            )
            self._recalculate_totals_locked()

    def update_subtask_progress(self, task_key, processed_count, success_count, failed_count, current_item=''):
        with self._lock:
            subtask = self._state.get('subtasks', {}).get(task_key)
            if subtask is None:
                return
            total_count = max(0, int(subtask.get('total_count', 0) or 0))
            processed_count = max(0, int(processed_count or 0))
            progress_percent = 0.0
            if total_count > 0:
                progress_percent = round((processed_count / total_count) * 100.0, 1)
            subtask.update(
                {
                    'processed_count': processed_count,
                    'success_count': max(0, int(success_count or 0)),
                    'failed_count': max(0, int(failed_count or 0)),
                    'current_item': str(current_item or ''),
                    'progress_percent': progress_percent,
                }
            )
            self._recalculate_totals_locked()

    def update_subtask_finish(self, task_key, message='', stopped=False, result=None):
        with self._lock:
            subtask = self._state.get('subtasks', {}).get(task_key)
            if subtask is None:
                return
            result = dict(result or {})
            processed_count = max(0, int(result.get('processed_count', subtask.get('processed_count', 0)) or 0))
            success_count = max(0, int(result.get('success_count', subtask.get('success_count', 0)) or 0))
            failed_count = max(0, int(result.get('failed_count', subtask.get('failed_count', 0)) or 0))
            total_count = max(0, int(subtask.get('total_count', 0) or 0))
            progress_percent = subtask.get('progress_percent', 0.0)
            if total_count > 0:
                progress_percent = round((processed_count / total_count) * 100.0, 1)
            subtask.update(
                {
                    'is_running': False,
                    'processed_count': processed_count,
                    'success_count': success_count,
                    'failed_count': failed_count,
                    'current_item': str(result.get('current_item', subtask.get('current_item', '')) or ''),
                    'remaining_count': max(0, int(result.get('remaining_count', subtask.get('remaining_count', 0)) or 0)),
                    'requires_manual_verification': bool(result.get('requires_manual_verification')),
                    'message': str(message or result.get('message', '') or ''),
                    'stopped': bool(stopped or result.get('stopped')),
                    'progress_percent': progress_percent,
                    'count_unit': str(result.get('count_unit', subtask.get('count_unit', '项')) or '项'),
                }
            )
            self._recalculate_totals_locked()

    def update_subtask_message(self, task_key, message='', *, is_running=None, current_item=None):
        with self._lock:
            subtask = self._state.get('subtasks', {}).get(task_key)
            if subtask is None:
                return
            subtask['message'] = str(message or '')
            if is_running is not None:
                subtask['is_running'] = bool(is_running)
            if current_item is not None:
                subtask['current_item'] = str(current_item or '')
            self._recalculate_totals_locked()

    def _recalculate_totals_locked(self):
        subtasks = list(self._state.get('subtasks', {}).values())
        total_count = sum(max(0, int(task.get('total_count', 0) or 0)) for task in subtasks)
        processed_count = sum(max(0, int(task.get('processed_count', 0) or 0)) for task in subtasks)
        success_count = sum(max(0, int(task.get('success_count', 0) or 0)) for task in subtasks)
        failed_count = sum(max(0, int(task.get('failed_count', 0) or 0)) for task in subtasks)
        remaining_count = sum(max(0, int(task.get('remaining_count', 0) or 0)) for task in subtasks)
        progress_percent = 0.0
        if total_count > 0:
            progress_percent = round((processed_count / total_count) * 100.0, 1)

        current_segments = []
        for task in subtasks:
            label = str(task.get('task_label', '') or '')
            current_item = str(task.get('current_item', '') or '')
            message = str(task.get('message', '') or '')
            if current_item:
                current_segments.append(f'{label}: {current_item}')
            elif task.get('is_running') and message:
                current_segments.append(f'{label}: {message}')

        self._state.update(
            {
                'total_count': total_count,
                'processed_count': processed_count,
                'success_count': success_count,
                'failed_count': failed_count,
                'remaining_count': remaining_count,
                'progress_percent': progress_percent,
                'current_item': ' | '.join(current_segments),
            }
        )

    @staticmethod
    def _build_subtask_state(task_definition):
        return {
            'task_key': task_definition['task_key'],
            'task_label': task_definition['task_label'],
            'target_type': task_definition['target_type'],
            'source_key': task_definition['source_key'],
            'source_label': '',
            'count_unit': str(task_definition.get('count_unit', '项') or '项'),
            'is_running': False,
            'total_count': 0,
            'processed_count': 0,
            'success_count': 0,
            'failed_count': 0,
            'remaining_count': 0,
            'current_item': '',
            'progress_percent': 0.0,
            'message': '',
            'stopped': False,
            'requires_manual_verification': False,
        }

    @staticmethod
    def _build_default_state():
        return {
            'is_running': False,
            'task_kind': '',
            'combo_key': '',
            'combo_label': '',
            'limit_per_task': 0,
            'target_label': '',
            'total_count': 0,
            'processed_count': 0,
            'success_count': 0,
            'failed_count': 0,
            'remaining_count': 0,
            'current_item': '',
            'progress_percent': 0.0,
            'message': '',
            'stopped': False,
            'log_path': '',
            'subtasks': {},
        }


class ComboSubtaskProgressTracker:
    def __init__(self, combo_progress_service, task_definition, logger):
        self.combo_progress_service = combo_progress_service
        self.task_definition = dict(task_definition)
        self.logger = logger

    def start(self, target_label, total_count, source_label='', message='', count_unit='项'):
        self.combo_progress_service.update_subtask_start(
            self.task_definition['task_key'],
            total_count,
            source_label=source_label,
            message=message,
            count_unit=count_unit,
        )
        self.logger.log(
            'INFO',
            '子任务开始处理候选项',
            task_key=self.task_definition['task_key'],
            task_label=self.task_definition['task_label'],
            total_count=max(0, int(total_count or 0)),
            source_label=str(source_label or ''),
            count_unit=str(count_unit or '项'),
        )

    def update(self, processed_count, success_count, failed_count, current_item=''):
        self.combo_progress_service.update_subtask_progress(
            self.task_definition['task_key'],
            processed_count,
            success_count,
            failed_count,
            current_item=current_item,
        )
        self.logger.log(
            'INFO',
            '子任务进度更新',
            task_key=self.task_definition['task_key'],
            processed_count=max(0, int(processed_count or 0)),
            success_count=max(0, int(success_count or 0)),
            failed_count=max(0, int(failed_count or 0)),
            current_item=str(current_item or ''),
        )

    def finish(self, message='', stopped=False):
        self.logger.log(
            'INFO',
            '子任务进度结束',
            task_key=self.task_definition['task_key'],
            stopped=bool(stopped),
            detail_message=str(message or ''),
        )

    def set_message(self, message):
        self.combo_progress_service.update_subtask_message(
            self.task_definition['task_key'],
            message=message,
        )

    def reset(self):
        return

from app.core.enrichment_sources import (
    DEFAULT_VIDEO_ENRICHMENT_SOURCE,
    JAVTXT_VIDEO_SOURCE,
    build_video_remaining_label,
    get_video_enrichment_source_label,
    normalize_video_enrichment_source,
)
from app.core.enrichment_status import ENRICHED_STATUS, FAILED_STATUS, NO_SEARCH_RESULTS_STATUS, UNENRICHED_STATUS
from app.core.enrichment_targets import VIDEO_LIBRARY_TARGET
from app.core.second_source_actor_text import normalize_second_source_actor_text
from app.scraper.avfan_scraper import AvfanScraper
from app.scraper.exceptions import HumanVerificationRequiredError
from app.scraper.javtxt_scraper import JavtxtScraper
from app.services.progress_tracker_compat import start_progress_tracker


class VideoSourceEnrichmentService:
    def __init__(
        self,
        database,
        source_key=DEFAULT_VIDEO_ENRICHMENT_SOURCE,
        scraper=None,
        show_browser=False,
        cooldown_before_search=False,
        should_stop=None,
        progress_tracker=None,
        logger=None,
    ):
        self.database = database
        self.source_key = normalize_video_enrichment_source(source_key)
        self.should_stop = should_stop or (lambda: False)
        self.progress_tracker = progress_tracker
        self.logger = logger
        self.scraper = scraper or self._build_scraper(show_browser, cooldown_before_search)

    def _build_scraper(self, show_browser, cooldown_before_search):
        if self.source_key == JAVTXT_VIDEO_SOURCE:
            return JavtxtScraper(headless=not show_browser, logger=self.logger)
        return AvfanScraper(
            headless=not show_browser,
            cooldown_before_search=cooldown_before_search,
        )

    def enrich_next_videos(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        candidates = self.database.list_videos_for_enrichment(limit, self.source_key)
        results = []
        success_count = 0
        failed_count = 0
        stopped = False
        source_label = get_video_enrichment_source_label(self.source_key)
        self._log(
            'INFO',
            '视频补全任务启动',
            source_key=self.source_key,
            source_label=source_label,
            requested_limit=limit,
            candidate_count=len(candidates),
            candidate_codes=','.join(video.get('code', '') for video in candidates[:20]),
        )

        if self.progress_tracker is not None:
            start_progress_tracker(
                self.progress_tracker,
                '视频库',
                len(candidates),
                source_label=source_label,
                count_unit='视频',
                target_type=VIDEO_LIBRARY_TARGET,
                source_key=self.source_key,
                log_path=str(getattr(self.logger, 'log_path', '') or ''),
                task_kind='single',
            )

        with self.scraper.session():
            for video in candidates:
                if self.should_stop():
                    stopped = True
                    self._log('WARNING', '视频补全收到停止请求', processed_count=len(results), source_key=self.source_key)
                    break

                code = video.get('code', '')
                self._log('INFO', '开始处理视频', code=code, source_key=self.source_key)
                try:
                    info = self.scraper.fetch_by_code(code)
                    if info.get('found'):
                        normalized_author = normalize_second_source_actor_text(
                            info.get('author', '') or info.get('javtxt_actors', '')
                        )
                        if self.source_key == JAVTXT_VIDEO_SOURCE and not normalized_author:
                            info = dict(info or {})
                            error_message = 'JAVTXT 未返回演员信息'
                            info['error'] = error_message
                            self.database.update_video_enrichment(
                                code,
                                info,
                                FAILED_STATUS,
                                source_key=self.source_key,
                            )
                            failed_count += 1
                            results.append(
                                {
                                    'code': code,
                                    'status': FAILED_STATUS,
                                    'error': error_message,
                                    'info': info,
                                }
                            )
                            self._log(
                                'WARNING',
                                '详情页已命中但演员解析为空，按失败写回',
                                code=code,
                                source_key=self.source_key,
                                status=FAILED_STATUS,
                                javtxt_movie_id=info.get('javtxt_movie_id', ''),
                                javtxt_url=info.get('javtxt_url', ''),
                            )
                        else:
                            self.database.update_video_enrichment(
                                code,
                                info,
                                ENRICHED_STATUS,
                                source_key=self.source_key,
                            )
                            success_count += 1
                            results.append(
                                {
                                    'code': code,
                                    'status': ENRICHED_STATUS,
                                    'info': info,
                                }
                            )
                            self._log(
                                'INFO',
                                '视频补全成功并写库',
                                code=code,
                                source_key=self.source_key,
                                status=ENRICHED_STATUS,
                                author=normalized_author,
                                release_date=info.get('release_date', ''),
                            )
                    else:
                        resolved_status = str(info.get('status', '') or NO_SEARCH_RESULTS_STATUS).strip() or NO_SEARCH_RESULTS_STATUS
                        error_message = info.get('error', '未搜索到匹配影片')
                        self.database.mark_video_no_search_results(
                            code,
                            error_message,
                            source_key=self.source_key,
                            status=resolved_status,
                        )
                        failed_count += 1
                        results.append(
                            {
                                'code': code,
                                'status': resolved_status,
                                'error': error_message,
                            }
                        )
                        self._log(
                            'WARNING',
                            '视频未搜索到可用详情，已写入终态状态',
                            code=code,
                            source_key=self.source_key,
                            status=resolved_status,
                            error=error_message,
                        )
                except HumanVerificationRequiredError as exc:
                    error_message = str(exc)
                    self.database.mark_video_enrichment_failed(
                        code,
                        error_message,
                        source_key=self.source_key,
                    )
                    failed_count += 1
                    results.append(
                        {
                            'code': code,
                            'status': FAILED_STATUS,
                            'error': error_message,
                        }
                    )
                    self._log(
                        'ERROR',
                        '视频补全被人机验证中断',
                        code=code,
                        source_key=self.source_key,
                        error=error_message,
                    )
                    self._update_progress(len(results), success_count, failed_count, code)
                    result = self._build_result(
                        limit,
                        results,
                        success_count,
                        failed_count,
                        True,
                        source_label,
                        requires_manual_verification=True,
                        message=error_message,
                    )
                    self._finish_progress(error_message, stopped=True)
                    return result
                except Exception as exc:
                    error_message = str(exc)
                    self.database.mark_video_enrichment_failed(
                        code,
                        error_message,
                        source_key=self.source_key,
                    )
                    failed_count += 1
                    results.append(
                        {
                            'code': code,
                            'status': FAILED_STATUS,
                            'error': error_message,
                        }
                    )
                    self._log(
                        'ERROR',
                        '视频补全异常，已写入失败状态',
                        code=code,
                        source_key=self.source_key,
                        error=error_message,
                    )

                self._update_progress(len(results), success_count, failed_count, code)

        result = self._build_result(limit, results, success_count, failed_count, stopped, source_label)
        self._finish_progress('视频补全已完成。' if not stopped else '视频补全已停止。', stopped=stopped)
        self._log(
            'INFO',
            '视频补全任务结束',
            source_key=self.source_key,
            processed_count=result['processed_count'],
            success_count=result['success_count'],
            failed_count=result['failed_count'],
            remaining_count=result['remaining_count'],
            stopped=stopped,
        )
        return result

    def _update_progress(self, processed_count, success_count, failed_count, current_item):
        if self.progress_tracker is not None:
            self.progress_tracker.update(
                processed_count=processed_count,
                success_count=success_count,
                failed_count=failed_count,
                current_item=current_item,
            )
        self._log(
            'INFO',
            '视频补全进度更新',
            source_key=self.source_key,
            processed_count=processed_count,
            success_count=success_count,
            failed_count=failed_count,
            current_item=current_item,
        )

    def _finish_progress(self, message, stopped=False):
        if self.progress_tracker is not None:
            self.progress_tracker.finish(message=message, stopped=stopped)

    def _build_result(
        self,
        limit,
        results,
        success_count,
        failed_count,
        stopped,
        source_label,
        requires_manual_verification=False,
        message='',
    ):
        if hasattr(self.database, 'count_pending_video_enrichments'):
            remaining_count = self.database.count_pending_video_enrichments(self.source_key)
        else:
            remaining_count = self.database.count_videos_by_enrichment_status(
                UNENRICHED_STATUS,
                source_key=self.source_key,
            ) + self.database.count_videos_by_enrichment_status(
                FAILED_STATUS,
                source_key=self.source_key,
            )
        return {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': remaining_count,
            'results': results,
            'stopped': stopped,
            'requires_manual_verification': requires_manual_verification,
            'message': message,
            'entity_label': '视频',
            'source_key': self.source_key,
            'source_label': source_label,
            'remaining_label': build_video_remaining_label(self.source_key),
        }

    def _log(self, level, message, **fields):
        if self.logger is not None:
            self.logger.log(level, message, service='video_source_enrichment', **fields)

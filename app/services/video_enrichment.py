from app.core.enrichment_status import (
    ENRICHED_STATUS,
    FAILED_STATUS,
    NO_SEARCH_RESULTS_STATUS,
    UNENRICHED_STATUS,
)
from app.scraper.avfan_scraper import AvfanScraper
from app.scraper.exceptions import HumanVerificationRequiredError


class VideoEnrichmentService:
    def __init__(
        self,
        database,
        scraper=None,
        show_browser=False,
        cooldown_before_search=False,
        should_stop=None,
    ):
        self.database = database
        self.should_stop = should_stop or (lambda: False)
        self.scraper = scraper or AvfanScraper(
            headless=not show_browser,
            cooldown_before_search=cooldown_before_search,
        )

    def enrich_next_videos(self, limit):
        limit = int(limit or 0)
        if limit <= 0:
            raise ValueError('补全数量必须大于 0')

        candidates = self.database.list_videos_for_enrichment(limit)
        results = []
        success_count = 0
        failed_count = 0
        stopped = False

        with self.scraper.session():
            for video in candidates:
                if self.should_stop():
                    stopped = True
                    break

                code = video.get('code', '')
                try:
                    info = self.scraper.fetch_by_code(code)
                    if info.get('found'):
                        self.database.update_video_enrichment(code, info, ENRICHED_STATUS)
                        success_count += 1
                        results.append({
                            'code': code,
                            'status': ENRICHED_STATUS,
                            'info': info,
                        })
                    else:
                        resolved_status = str(info.get('status', '') or NO_SEARCH_RESULTS_STATUS).strip() or NO_SEARCH_RESULTS_STATUS
                        error_message = info.get('error', '未搜索到匹配影片')
                        self.database.mark_video_no_search_results(code, error_message, status=resolved_status)
                        failed_count += 1
                        results.append({
                            'code': code,
                            'status': resolved_status,
                            'error': error_message,
                        })
                except HumanVerificationRequiredError as exc:
                    error_message = str(exc)
                    self.database.mark_video_enrichment_failed(code, error_message)
                    failed_count += 1
                    results.append({
                        'code': code,
                        'status': FAILED_STATUS,
                        'error': error_message,
                    })
                    return {
                        'requested': limit,
                        'processed_count': len(results),
                        'success_count': success_count,
                        'failed_count': failed_count,
                        'remaining_count': self.database.count_videos_by_enrichment_status(UNENRICHED_STATUS),
                        'results': results,
                        'stopped': True,
                        'requires_manual_verification': True,
                        'message': error_message,
                        'entity_label': '视频',
                        'remaining_label': '剩余未补全视频',
                    }
                except Exception as exc:
                    self.database.mark_video_enrichment_failed(code, str(exc))
                    failed_count += 1
                    results.append({
                        'code': code,
                        'status': FAILED_STATUS,
                        'error': str(exc),
                    })

        return {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': self.database.count_videos_by_enrichment_status(UNENRICHED_STATUS),
            'results': results,
            'stopped': stopped,
            'entity_label': '视频',
            'remaining_label': '剩余未补全视频',
        }

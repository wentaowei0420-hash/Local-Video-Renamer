from avfan_scraper import AvfanScraper


class VideoEnrichmentService:
    def __init__(self, database, scraper=None, show_browser=False, cooldown_before_search=False):
        self.database = database
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

        with self.scraper.session():
            for video in candidates:
                code = video.get('code', '')
                try:
                    info = self.scraper.fetch_by_code(code)
                    if info.get('found'):
                        self.database.update_video_enrichment(code, info, '已补全')
                        success_count += 1
                        results.append({
                            'code': code,
                            'status': '已补全',
                            'info': info,
                        })
                    else:
                        self.database.update_video_enrichment(code, info, '补全失败')
                        failed_count += 1
                        results.append({
                            'code': code,
                            'status': '补全失败',
                            'error': info.get('error', '未搜索到匹配影片'),
                        })
                except Exception as exc:
                    self.database.mark_video_enrichment_failed(code, str(exc))
                    failed_count += 1
                    results.append({
                        'code': code,
                        'status': '补全失败',
                        'error': str(exc),
                    })

        return {
            'requested': limit,
            'processed_count': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'remaining_count': self.database.count_videos_by_enrichment_status('未补全'),
            'results': results,
        }

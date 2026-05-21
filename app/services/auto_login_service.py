from app.scraper.avfan_scraper import AvfanScraper
from app.scraper.login_status_service import ensure_logged_in_on_home


class AutoLoginService:
    def __init__(self, scraper=None):
        self.scraper = scraper or AvfanScraper(headless=False)

    def run(self):
        self.scraper.open_session()
        page = self.scraper.get_page(self.scraper._context)
        try:
            result = ensure_logged_in_on_home(page, headless=False)
            return {
                'success': True,
                'message': result.get('message', '已完成登录状态检查。'),
                'status': result.get('status', ''),
                'auto_login_triggered': bool(result.get('auto_login_triggered')),
                'current_url': page.url,
            }
        finally:
            self.scraper.close_session()

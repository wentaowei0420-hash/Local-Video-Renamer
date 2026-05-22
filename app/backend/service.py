from pathlib import Path
from threading import Event, Lock

from app.api.video_renamer_api import VideoRenamerAPI
from app.core.project_paths import ACTOR_CSV_FILE, DATABASE_FILE, PROJECT_ROOT, VIDEO_CSV_FILE
from app.core.video_models import plan_from_dict, plan_to_dict, result_to_dict
from app.data.database_handler import VideoDatabase
from app.scraper.avfan_scraper import reset_avfan_browser_profile
from app.services.actor_detail_library import ActorDetailLibrary
from app.services.actor_identifier import ActorIdentifier
from app.services.auto_login_service import AutoLoginService
from app.services.code_prefix_library import CodePrefixLibrary
from app.services.path_library import PathLibrary, summarize_paths
from app.services.video_enrichment import VideoEnrichmentService


class BackendService:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or PROJECT_ROOT)
        self.csv_path = VIDEO_CSV_FILE
        self.actor_csv_path = ACTOR_CSV_FILE
        self.db = VideoDatabase(DATABASE_FILE)
        self.renamer = VideoRenamerAPI(self.csv_path)
        self.actor_identifier = ActorIdentifier(self.actor_csv_path)
        self.actor_detail_library = ActorDetailLibrary(self.db)
        self.code_prefix_library = CodePrefixLibrary(self.db)
        self.path_library = PathLibrary()
        self.database_loaded = False
        self.actor_profiles_loaded = False
        self.enrichment_cancel_event = Event()
        self.enrichment_lock = Lock()
        self.enrichment_running = False

    def load_database(self):
        video_db = self.renamer.load_database()
        actor_profiles = self.actor_identifier.load_profiles()
        self.database_loaded = True
        self.actor_profiles_loaded = True
        return {
            'count': len(video_db),
            'actor_count': len(actor_profiles),
            'csv_path': str(self.csv_path),
            'actor_csv_path': str(self.actor_csv_path),
        }

    def ensure_database_loaded(self):
        if not self.database_loaded:
            self.load_database()

    def health(self):
        return {
            'ok': True,
            'database_loaded': self.database_loaded,
            'actor_profiles_loaded': self.actor_profiles_loaded,
            'csv_exists': self.csv_path.exists(),
            'actor_csv_exists': self.actor_csv_path.exists(),
            'csv_path': str(self.csv_path),
            'actor_csv_path': str(self.actor_csv_path),
            'db_path': str(self.db.db_path),
            'enrichment_running': self.enrichment_running,
        }

    def scan(self, folder_path):
        self.ensure_database_loaded()
        plans = self.renamer.scan_folder(folder_path)
        return {
            'plans': [plan_to_dict(plan) for plan in plans],
            'count': len(plans),
            'rename_count': sum(1 for plan in plans if plan.needs_rename),
        }

    def rename(self, plans_data):
        plans = [plan_from_dict(plan) for plan in plans_data]
        results = self.renamer.execute_renames(plans)
        return {
            'results': [result_to_dict(result) for result in results],
            'success_count': sum(1 for result in results if result.success and result.message == '完成'),
        }

    def save_plans(self, plans_data):
        plans = [plan_from_dict(plan) for plan in plans_data]
        video_count = self.db.save_plans(plans)
        actors = self.actor_identifier.identify_from_plans(plans)
        actor_count = self.db.save_actors(actors)
        return {
            'success_count': video_count,
            'actor_count': actor_count,
        }

    def list_videos(self, search_text=''):
        return {'videos': self.db.list_videos(search_text)}

    def get_video_enrichment_summary(self):
        return {'summary': self.db.get_video_enrichment_summary()}

    def list_actors(self, search_text=''):
        return {'actors': self.db.list_actors(search_text)}

    def get_actor_detail(self, actor_name):
        return {'actor': self.actor_detail_library.get_actor_detail(actor_name)}

    def list_code_prefixes(self, search_text=''):
        return {'prefixes': self.code_prefix_library.list_prefixes(search_text)}

    def list_paths(self):
        paths = []
        for record in self.db.list_paths():
            path_record = self.path_library.with_exists_status(record)
            if path_record.get('exists'):
                self.db.update_path_storage_info(path_record['id'], path_record)
            paths.append(path_record)

        return {
            'paths': paths,
            'summary': summarize_paths(paths),
        }

    def add_path(self, folder_path):
        path_record = self.path_library.build_path_record(folder_path)
        saved_record = self.db.add_path(path_record['path'])
        enriched_record = self.path_library.with_exists_status(saved_record)
        self.db.update_path_storage_info(enriched_record['id'], enriched_record)
        return {'path': enriched_record}

    def delete_path(self, path_id):
        if path_id is None:
            raise ValueError('缺少 path_id')
        return {'deleted_count': self.db.delete_path(path_id)}

    def enrich_videos(self, limit, show_browser=False, cooldown_before_search=False):
        with self.enrichment_lock:
            if self.enrichment_running:
                raise RuntimeError('已有补全任务正在运行，请稍后再试。')
            self.enrichment_running = True
            self.enrichment_cancel_event.clear()

        try:
            enrichment_service = VideoEnrichmentService(
                self.db,
                show_browser=show_browser,
                cooldown_before_search=cooldown_before_search,
                should_stop=self.enrichment_cancel_event.is_set,
            )
            return enrichment_service.enrich_next_videos(limit)
        finally:
            self.enrichment_running = False
            self.enrichment_cancel_event.clear()

    def cancel_enrichment(self):
        if not self.enrichment_running:
            return {
                'cancel_requested': False,
                'message': '当前没有正在运行的补全任务。',
            }
        self.enrichment_cancel_event.set()
        return {
            'cancel_requested': True,
            'message': '已请求停止补全，当前视频处理完成后会停止。',
        }

    def auto_login(self):
        return AutoLoginService().run()

    def reset_browser_profile(self):
        return reset_avfan_browser_profile()

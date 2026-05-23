from pathlib import Path
from threading import Event, Lock

from app.core.enrichment_targets import ACTOR_LIBRARY_TARGET, VIDEO_LIBRARY_TARGET
from app.core.project_paths import DATABASE_FILE, PROJECT_ROOT
from app.data.database_handler import VideoDatabase
from app.scraper.avfan_scraper import reset_avfan_browser_profile
from app.services.actor_detail_library import ActorDetailLibrary
from app.services.actor_library_sync_service import ActorLibrarySyncService
from app.services.auto_login_service import AutoLoginService
from app.services.code_prefix_detail_library import CodePrefixDetailLibrary
from app.services.code_prefix_library import CodePrefixLibrary
from app.services.data_center_service import DataCenterService
from app.services.library_admin_service import LibraryAdminService
from app.services.library_enrichment_service import LibraryEnrichmentService
from app.services.local_video_library_service import LocalVideoLibraryService
from app.services.path_library import PathLibrary, summarize_paths


class BackendService:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or PROJECT_ROOT)
        self.db = VideoDatabase(DATABASE_FILE)
        self.local_video_library = LocalVideoLibraryService(self.db)
        self.actor_detail_library = ActorDetailLibrary(self.db)
        self.actor_library_sync_service = ActorLibrarySyncService(self.db)
        self.code_prefix_detail_library = CodePrefixDetailLibrary(self.db)
        self.code_prefix_library = CodePrefixLibrary(self.db)
        self.data_center_service = DataCenterService(self.db)
        self.library_admin_service = LibraryAdminService(self.db)
        self.path_library = PathLibrary()
        self.database_loaded = False
        self.enrichment_cancel_event = Event()
        self.enrichment_lock = Lock()
        self.enrichment_running = False

    def load_database(self):
        self.actor_library_sync_service.sync_from_video_library()
        self.database_loaded = True
        return {
            'count': self.db.get_video_count(),
            'actor_count': self.db.get_actor_count(),
            'db_path': str(self.db.db_path),
        }

    def ensure_database_loaded(self):
        if not self.database_loaded:
            self.load_database()

    def health(self):
        return {
            'ok': True,
            'database_loaded': self.database_loaded,
            'db_path': str(self.db.db_path),
            'enrichment_running': self.enrichment_running,
        }

    def scan(self, folder_path):
        self.ensure_database_loaded()
        return self.local_video_library.scan_folder(folder_path)

    def rename(self, plans_data):
        return self.local_video_library.execute_renames(plans_data)

    def import_videos(self, plans_data):
        self.ensure_database_loaded()
        return {'success_count': self.local_video_library.import_videos(plans_data)}

    def list_videos(self, search_text=''):
        return {'videos': self.db.list_videos(search_text)}

    def get_video_enrichment_summary(self):
        return {'summary': self.db.get_video_enrichment_summary()}

    def get_data_center_summary(self):
        self.ensure_database_loaded()
        return {'summary': self.data_center_service.get_summary()}

    def reset_video_enrichments(self, codes):
        return {'reset_count': self.db.reset_video_enrichments(codes)}

    def list_actors(self, search_text=''):
        self.ensure_database_loaded()
        return {'actors': self.db.list_actors(search_text)}

    def get_actor_detail(self, actor_name):
        return {'actor': self.actor_detail_library.get_actor_detail(actor_name)}

    def reset_actor_enrichments(self, actor_names):
        return {'reset_count': self.db.reset_actor_enrichments(actor_names)}

    def rename_actor(self, old_name, new_name):
        return {'updated_count': self.library_admin_service.rename_actor(old_name, new_name)}

    def delete_actor(self, actor_name):
        return {'deleted_count': self.library_admin_service.delete_actor(actor_name)}

    def list_code_prefixes(self, search_text=''):
        return {'prefixes': self.code_prefix_library.list_prefixes(search_text)}

    def get_code_prefix_detail(self, prefix):
        return {'prefix_detail': self.code_prefix_detail_library.get_prefix_detail(prefix)}

    def reset_code_prefix_enrichments(self, prefixes):
        return {'reset_count': self.db.reset_code_prefix_enrichments(prefixes)}

    def rename_code_prefix(self, old_prefix, new_prefix):
        return {'updated_count': self.library_admin_service.rename_code_prefix(old_prefix, new_prefix)}

    def delete_code_prefix(self, prefix):
        return {'deleted_count': self.library_admin_service.delete_code_prefix(prefix)}

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

    def enrich_videos(self, limit, show_browser=False, cooldown_before_search=False, target_type=None, source_key=None):
        with self.enrichment_lock:
            if self.enrichment_running:
                raise RuntimeError('已有补全任务正在运行，请稍后再试。')
            self.enrichment_running = True
            self.enrichment_cancel_event.clear()

        try:
            enrichment_service = LibraryEnrichmentService(
                self.db,
                show_browser=show_browser,
                cooldown_before_search=cooldown_before_search,
                should_stop=self.enrichment_cancel_event.is_set,
            )
            if target_type == ACTOR_LIBRARY_TARGET:
                self.actor_library_sync_service.sync_from_video_library()

            result = enrichment_service.run(target_type, limit, source_key=source_key)

            if (not target_type or target_type == VIDEO_LIBRARY_TARGET) and result.get('processed_count', 0) > 0:
                self.actor_library_sync_service.sync_from_video_library()

            return result
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
            'message': '已请求停止补全，当前条目处理完成后会停止。',
        }

    def auto_login(self):
        return AutoLoginService().run()

    def reset_browser_profile(self):
        return reset_avfan_browser_profile()

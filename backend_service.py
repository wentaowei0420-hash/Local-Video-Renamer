from pathlib import Path

from actor_identifier import ActorIdentifier
from database_handler import VideoDatabase
from path_library import PathLibrary, summarize_paths
from video_enrichment import VideoEnrichmentService
from video_models import plan_from_dict, plan_to_dict, result_to_dict
from video_renamer_api import VideoRenamerAPI


class BackendService:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent)
        self.csv_path = self.base_dir / '目录统计 - 详细介绍.csv'
        self.actor_csv_path = self.base_dir / '目录统计 - 演员统计.csv'
        self.db = VideoDatabase(self.base_dir / 'video_database.db')
        self.renamer = VideoRenamerAPI(self.csv_path)
        self.actor_identifier = ActorIdentifier(self.actor_csv_path)
        self.path_library = PathLibrary()
        self.database_loaded = False
        self.actor_profiles_loaded = False

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

    def list_actors(self, search_text=''):
        return {'actors': self.db.list_actors(search_text)}

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

    def enrich_videos(self, limit):
        enrichment_service = VideoEnrichmentService(self.db)
        return enrichment_service.enrich_next_videos(limit)

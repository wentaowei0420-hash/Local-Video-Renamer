from pathlib import Path

from csv_video_loader import load_video_database
from filename_rules import (
    DEFAULT_VIDEO_EXTS,
    build_normalized_filename,
    clean_video_title,
    extract_code_from_filename,
    normalize_text_spacing,
    strip_title_suffix_noise,
)
from path_library import get_storage_location_name
from video_models import (
    RenamePlan,
    RenameResult,
    VideoMetadata,
    metadata_from_dict,
    metadata_to_dict,
    plan_from_dict,
    plan_to_dict,
    result_to_dict,
)


class VideoRenamerAPI:
    def __init__(self, csv_path, video_exts=DEFAULT_VIDEO_EXTS):
        self.csv_path = Path(csv_path)
        self.video_exts = tuple(ext.lower() for ext in video_exts)
        self.video_db = {}

    def load_database(self):
        self.video_db = load_video_database(self.csv_path)
        return self.video_db

    def scan_folder(self, folder_path):
        folder_path = Path(folder_path)
        if not folder_path.exists() or not folder_path.is_dir():
            raise FileNotFoundError(f'文件夹不存在: {folder_path}')

        storage_location = get_storage_location_name(folder_path)
        plans = []
        for file_path in folder_path.rglob('*'):
            if not file_path.is_file() or file_path.suffix.lower() not in self.video_exts:
                continue

            print(f"正在扫描: {file_path.name}")
            code = extract_code_from_filename(file_path.stem)

            if not code:
                continue
            if code not in self.video_db:
                print(f"  -> ❌ 被踢出: CSV 数据库里没有 {code} 这个编号的数据！")
                continue

            metadata = self.video_db[code]
            new_name = build_normalized_filename(metadata, file_path.suffix)
            new_path = file_path.parent / new_name
            plans.append(RenamePlan(file_path, new_path, metadata, storage_location))

        return plans

    def execute_renames(self, plans):
        results = []
        for plan in plans:
            try:
                if not plan.needs_rename:
                    results.append(RenameResult(plan, True, '已规范，无需修改'))
                    continue

                if plan.new_path.exists():
                    results.append(RenameResult(plan, False, '目标已存在'))
                    continue

                plan.old_path.rename(plan.new_path)
                results.append(RenameResult(plan, True, '完成'))
            except Exception as exc:
                results.append(RenameResult(plan, False, '错误', str(exc)))

        return results

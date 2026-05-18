from pathlib import Path


class PathLibrary:
    def normalize_path(self, folder_path):
        folder_path = (folder_path or '').strip()
        if not folder_path:
            raise ValueError('路径不能为空')

        return str(Path(folder_path).expanduser().resolve())

    def build_path_record(self, folder_path):
        normalized_path = self.normalize_path(folder_path)
        path_obj = Path(normalized_path)

        if not path_obj.exists() or not path_obj.is_dir():
            raise FileNotFoundError(f'文件夹不存在: {normalized_path}')

        return {
            'path': normalized_path,
            'exists': True,
        }

    def with_exists_status(self, record):
        path_text = record.get('path', '')
        path_obj = Path(path_text)
        record = dict(record)
        record['exists'] = path_obj.exists() and path_obj.is_dir()
        return record

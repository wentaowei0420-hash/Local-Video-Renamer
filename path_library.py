import ctypes
import os
import shutil
from pathlib import Path
from pathlib import PureWindowsPath


DRIVE_TYPES = {
    0: '未知',
    1: '无根路径',
    2: 'U盘/可移动盘',
    3: '本地磁盘',
    4: '网络磁盘',
    5: '光驱',
    6: '内存盘',
}


class PathLibrary:
    def normalize_path(self, folder_path):
        folder_path = str(folder_path or '').strip()
        if not folder_path:
            raise ValueError('路径不能为空')

        path_obj = Path(folder_path).expanduser()
        if not path_obj.is_absolute():
            path_obj = Path.cwd() / path_obj

        normalized_path = str(path_obj)
        if os.name == 'nt':
            normalized_path = str(PureWindowsPath(normalized_path))

        return normalized_path.rstrip('\\/')

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
        exists = path_obj.exists() and path_obj.is_dir()
        record['exists'] = exists
        if exists:
            record.update(self.get_storage_info(path_text))
            record['uses_last_snapshot'] = False
        else:
            record.update(last_storage_info(record))
            record['uses_last_snapshot'] = has_last_storage_info(record)
        return record

    def get_storage_info(self, folder_path):
        total, used, free = shutil.disk_usage(folder_path)
        usage_percent = round((used / total) * 100, 1) if total else 0
        drive_type = get_drive_type(folder_path)

        return {
            'volume_type': DRIVE_TYPES.get(drive_type, '未知'),
            'is_removable': drive_type == 2,
            'total_bytes': total,
            'used_bytes': used,
            'free_bytes': free,
            'total': format_bytes(total),
            'used': format_bytes(used),
            'free': format_bytes(free),
            'usage_percent': usage_percent,
        }


def get_storage_location_name(folder_path):
    normalized_path = PathLibrary().normalize_path(folder_path)
    return Path(normalized_path).name or normalized_path


def summarize_paths(paths):
    total_bytes = sum(int(path.get('total_bytes') or 0) for path in paths)
    used_bytes = sum(int(path.get('used_bytes') or 0) for path in paths)
    free_bytes = sum(int(path.get('free_bytes') or 0) for path in paths)
    usage_percent = round((used_bytes / total_bytes) * 100, 1) if total_bytes else 0

    return {
        'total_bytes': total_bytes,
        'used_bytes': used_bytes,
        'free_bytes': free_bytes,
        'total': format_bytes(total_bytes),
        'used': format_bytes(used_bytes),
        'free': format_bytes(free_bytes),
        'usage_percent': usage_percent,
        'path_count': len(paths),
        'connected_count': sum(1 for path in paths if path.get('exists')),
    }


def has_last_storage_info(record):
    return bool(record.get('last_total_bytes') or record.get('last_used_bytes') or record.get('last_free_bytes'))


def last_storage_info(record):
    if not has_last_storage_info(record):
        return empty_storage_info()

    total_bytes = int(record.get('last_total_bytes') or 0)
    used_bytes = int(record.get('last_used_bytes') or 0)
    free_bytes = int(record.get('last_free_bytes') or 0)
    usage_percent = record.get('last_usage_percent') or 0

    return {
        'volume_type': record.get('last_volume_type') or '上次记录',
        'is_removable': False,
        'total_bytes': total_bytes,
        'used_bytes': used_bytes,
        'free_bytes': free_bytes,
        'total': format_bytes(total_bytes),
        'used': format_bytes(used_bytes),
        'free': format_bytes(free_bytes),
        'usage_percent': usage_percent,
    }


def empty_storage_info():
    return {
        'volume_type': '不可用',
        'is_removable': False,
        'total_bytes': 0,
        'used_bytes': 0,
        'free_bytes': 0,
        'total': '',
        'used': '',
        'free': '',
        'usage_percent': '',
    }


def format_bytes(size):
    size = float(size or 0)
    units = ('B', 'KB', 'MB', 'GB', 'TB', 'PB')

    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == 'B':
                return f'{int(size)} {unit}'
            return f'{size:.2f} {unit}'
        size /= 1024

    return f'{size:.2f} PB'


def get_drive_type(folder_path):
    if os.name != 'nt':
        return 3

    try:
        volume_root = ctypes.create_unicode_buffer(260)
        result = ctypes.windll.kernel32.GetVolumePathNameW(
            str(folder_path),
            volume_root,
            len(volume_root),
        )
        root_path = volume_root.value if result else str(Path(folder_path).anchor)
        if root_path and not root_path.endswith('\\'):
            root_path += '\\'
        return ctypes.windll.kernel32.GetDriveTypeW(root_path)
    except Exception:
        return 0

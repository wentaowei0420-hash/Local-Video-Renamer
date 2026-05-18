import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.wmv', '.mov')
TITLE_EDGE_CHARS = r'\s\-_【】\[\]{}()（）《》<>""''“”‘’.,。，！？!?~、；;：:'
VIDEO_SUFFIX_RE = re.compile(r'\.(mp4|mkv|avi|wmv|mov)\s*$', re.I)


@dataclass(frozen=True)
class VideoMetadata:
    code: str
    title: str
    author: str
    duration: str
    size: str


@dataclass(frozen=True)
class RenamePlan:
    old_path: Path
    new_path: Path
    metadata: VideoMetadata

    @property
    def old_name(self):
        return self.old_path.name

    @property
    def new_name(self):
        return self.new_path.name

    @property
    def needs_rename(self):
        return self.old_name != self.new_name


@dataclass(frozen=True)
class RenameResult:
    plan: RenamePlan
    success: bool
    message: str
    error: str = ''


def strip_title_suffix_noise(title):
    previous = None
    clean_title = title
    while clean_title != previous:
        previous = clean_title
        clean_title = VIDEO_SUFFIX_RE.sub('', clean_title)
        clean_title = re.sub(
            rf'^[{TITLE_EDGE_CHARS}]+|[{TITLE_EDGE_CHARS}]+$',
            '',
            clean_title,
        )
    return clean_title.strip()


def normalize_text_spacing(text):
    return re.sub(r'\s+', ' ', text).strip()


def clean_video_title(code, author, raw_name):
    clean_title = re.sub(re.escape(code), '', raw_name, flags=re.I)
    if author:
        clean_title = clean_title.replace(author, '')

    clean_title = normalize_text_spacing(strip_title_suffix_noise(clean_title))

    if not clean_title:
        clean_title = normalize_text_spacing(strip_title_suffix_noise(raw_name))

    return clean_title


def extract_code_from_filename(filename):
    # 增强版正则：支持 CMV-001, CMV_001, CMV 001, CMV001 等各种格式
    match = re.search(r'([a-zA-Z]+)[-_ ]?(\d+)', filename)
    if match:
        letters = match.group(1).upper()
        numbers = match.group(2)
        return f"{letters}-{numbers}"
    return None


def load_video_database(csv_path):
    csv_path = Path(csv_path)
    video_db = {}

    if not csv_path.exists():
        raise FileNotFoundError(f'未找到 CSV 数据库文件: {csv_path}')

    with csv_path.open(mode='r', encoding='utf-8-sig', errors='ignore', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row.get('系列名称', '').strip()
            author = normalize_text_spacing(row.get('演员', ''))
            raw_name = row.get('名称', '').strip()
            duration = row.get('时长(可读)', '').strip()
            size = row.get('大小(GB)', '').strip()

            if not code:
                continue

            normalized_code = code.upper()
            video_db[normalized_code] = VideoMetadata(
                code=normalized_code,
                title=clean_video_title(code, author, raw_name),
                author=author,
                duration=duration,
                size=size
            )
    return video_db


def build_normalized_filename(metadata, extension):
    # 修复空括号问题：如果没有作者，则不拼接 -{}
    if metadata.author:
        return f"【{metadata.code}】-{metadata.title}-{{{metadata.author}}}{extension}"
    else:
        return f"【{metadata.code}】-{metadata.title}{extension}"


def metadata_to_dict(metadata):
    return {
        'code': metadata.code,
        'title': metadata.title,
        'author': metadata.author,
        'duration': metadata.duration,
        'size': metadata.size,
    }


def metadata_from_dict(data):
    return VideoMetadata(
        code=data.get('code', ''),
        title=data.get('title', ''),
        author=data.get('author', ''),
        duration=data.get('duration', ''),
        size=data.get('size', ''),
    )


def plan_to_dict(plan):
    return {
        'old_path': str(plan.old_path),
        'new_path': str(plan.new_path),
        'old_name': plan.old_name,
        'new_name': plan.new_name,
        'needs_rename': plan.needs_rename,
        'metadata': metadata_to_dict(plan.metadata),
    }


def plan_from_dict(data):
    return RenamePlan(
        old_path=Path(data['old_path']),
        new_path=Path(data['new_path']),
        metadata=metadata_from_dict(data.get('metadata', {})),
    )


def result_to_dict(result):
    return {
        'plan': plan_to_dict(result.plan),
        'success': result.success,
        'message': result.message,
        'error': result.error,
    }


class VideoRenamerAPI:
    def __init__(self, csv_path, video_exts=DEFAULT_VIDEO_EXTS):
        self.csv_path = Path(csv_path)
        self.video_exts = tuple(ext.lower() for ext in video_exts)
        self.video_db = {}
        # 这里不再初始化数据库！

    def load_database(self):
        self.video_db = load_video_database(self.csv_path)
        return self.video_db

    def scan_folder(self, folder_path):
        folder_path = Path(folder_path)
        if not folder_path.exists() or not folder_path.is_dir():
            raise FileNotFoundError(f'文件夹不存在: {folder_path}')

        plans = []
        for file_path in folder_path.rglob('*'):
            if not file_path.is_file() or file_path.suffix.lower() not in self.video_exts:
                continue

            # 保留了打印监控，方便你排查问题
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
            plans.append(RenamePlan(file_path, new_path, metadata))

        return plans

    def execute_renames(self, plans):
        results = []
        for plan in plans:
            try:
                # 如果不需要改名，直接跳过并标记成功
                if not plan.needs_rename:
                    results.append(RenameResult(plan, True, '已规范，无需修改'))
                    continue

                # 如果目标文件已存在，标记报错
                if plan.new_path.exists():
                    results.append(RenameResult(plan, False, '目标已存在'))
                    continue

                # 仅仅执行物理重命名操作
                plan.old_path.rename(plan.new_path)
                results.append(RenameResult(plan, True, '完成'))
            except Exception as exc:
                results.append(RenameResult(plan, False, '错误', str(exc)))

        return results

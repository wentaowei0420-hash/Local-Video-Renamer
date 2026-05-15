import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path

# 引入我们刚才新建的数据存储层
from database import VideoDatabase

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
    match = re.search(r'([a-zA-Z]+-\d+)', filename)
    if match:
        return match.group(1).upper()
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
    return f"【{metadata.code}】-{metadata.title}-{{{metadata.author}}}{extension}"


class VideoRenamerAPI:
    def __init__(self, csv_path, video_exts=DEFAULT_VIDEO_EXTS, db_path='video_database.db'):
        self.csv_path = Path(csv_path)
        self.video_exts = tuple(ext.lower() for ext in video_exts)
        self.video_db = {}

        # 实例化数据存储层 (依赖注入)
        self.db = VideoDatabase(db_path)

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

            code = extract_code_from_filename(file_path.stem)
            if not code or code not in self.video_db:
                continue

            metadata = self.video_db[code]
            new_name = build_normalized_filename(metadata, file_path.suffix)
            new_path = file_path.parent / new_name

            if new_name != file_path.name:
                plans.append(RenamePlan(file_path, new_path, metadata))

        return plans

    def execute_renames(self, plans):
        results = []

        for plan in plans:
            try:
                if plan.new_path.exists():
                    results.append(RenameResult(plan, False, '目标已存在'))
                    continue

                # 1. 物理重命名文件
                plan.old_path.rename(plan.new_path)

                # 2. 调用存储层写入数据 (API 不再关心 SQL 语句怎么写)
                self.db.save_processed_video(
                    code=plan.metadata.code,
                    title=plan.metadata.title,
                    author=plan.metadata.author,
                    duration=plan.metadata.duration,
                    size=plan.metadata.size
                )

                results.append(RenameResult(plan, True, '完成'))
            except Exception as exc:
                results.append(RenameResult(plan, False, '错误', str(exc)))

        return results
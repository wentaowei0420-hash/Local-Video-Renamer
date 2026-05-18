from dataclasses import dataclass
from pathlib import Path


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
    storage_location: str = ''

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
        'storage_location': plan.storage_location,
        'metadata': metadata_to_dict(plan.metadata),
    }


def plan_from_dict(data):
    return RenamePlan(
        old_path=Path(data['old_path']),
        new_path=Path(data['new_path']),
        metadata=metadata_from_dict(data.get('metadata', {})),
        storage_location=data.get('storage_location', ''),
    )


def result_to_dict(result):
    return {
        'plan': plan_to_dict(result.plan),
        'success': result.success,
        'message': result.message,
        'error': result.error,
    }

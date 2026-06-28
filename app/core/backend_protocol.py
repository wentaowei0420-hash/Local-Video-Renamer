from hashlib import sha256
from pathlib import Path


BACKEND_API_REVISION = (
    '2026-06-28-'
    'binghuo-backend-guard-actor-update-status-'
    'actor-library-status-actor-detail-birthday-display-'
    'data-center-analysis-cache-binghuo-no-detail-'
    'manual-snapshot-paged-query-issue-list-'
    'batch-auto-stop-code-prefix-analysis-'
    'actor-library-baomu-age-co-star-code-filter-'
    'actor-detail-refresh-guard-1'
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BACKEND_FINGERPRINT_TARGETS = (
    'backend_server.py',
    'app/backend',
    'app/core',
    'app/data',
    'app/scraper',
    'app/services',
)


def _iter_backend_fingerprint_files(project_root=None):
    base_dir = Path(project_root or _PROJECT_ROOT).resolve()
    files = []
    for relative_target in _BACKEND_FINGERPRINT_TARGETS:
        target_path = base_dir / relative_target
        if target_path.is_file():
            files.append(target_path)
            continue
        if target_path.is_dir():
            files.extend(path for path in target_path.rglob('*.py') if path.is_file())
    return sorted(files, key=lambda path: path.relative_to(base_dir).as_posix())


def build_backend_code_fingerprint(project_root=None):
    base_dir = Path(project_root or _PROJECT_ROOT).resolve()
    digest = sha256()
    digest.update(BACKEND_API_REVISION.encode('utf-8'))
    for file_path in _iter_backend_fingerprint_files(base_dir):
        relative_path = file_path.relative_to(base_dir).as_posix()
        stat = file_path.stat()
        digest.update(relative_path.encode('utf-8'))
        digest.update(str(int(stat.st_mtime_ns)).encode('utf-8'))
        digest.update(str(int(stat.st_size)).encode('utf-8'))
    return digest.hexdigest()


BACKEND_PROCESS_CODE_FINGERPRINT = build_backend_code_fingerprint()

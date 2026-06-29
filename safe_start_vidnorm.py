import argparse
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

from app.backend.client import BackendClient
from app.core.backend_protocol import BACKEND_API_REVISION, build_backend_code_fingerprint
from app.core.project_paths import DATABASE_FILE, PROJECT_ROOT, TASK_TRACE_LOG_DIR
from app.core.runtime_config import get_backend_port, get_backend_timeout_seconds


BACKEND_INSTANCE_TOKEN_ENV = 'VIDNORM_BACKEND_INSTANCE_TOKEN'
BACKEND_OWNED_ENV = 'VIDNORM_BACKEND_OWNED'
STARTUP_LOG_FILE = TASK_TRACE_LOG_DIR / 'startup_launcher.log'


def is_matching_backend_code(health):
    if str((health or {}).get('backend_revision') or '').strip() != BACKEND_API_REVISION:
        return False
    return str((health or {}).get('backend_code_fingerprint') or '').strip() == build_backend_code_fingerprint(PROJECT_ROOT)


def is_project_backend(health):
    if not health or not is_matching_backend_code(health):
        return False
    project_root = str((health or {}).get('project_root') or '').strip()
    if not project_root:
        return False
    return Path(project_root).resolve() == PROJECT_ROOT.resolve()


def is_expected_backend(health, instance_token):
    return is_project_backend(health) and str((health or {}).get('backend_instance_token') or '').strip() == str(
        instance_token or ''
    ).strip()


def build_gui_environment(base_env, instance_token, owns_backend):
    gui_env = dict(base_env or {})
    gui_env[BACKEND_INSTANCE_TOKEN_ENV] = str(instance_token or '').strip()
    gui_env[BACKEND_OWNED_ENV] = '1' if owns_backend else '0'
    return gui_env


def choose_gui_interpreter(console_python):
    console_path = Path(console_python)
    if console_path.name.lower() == 'python.exe':
        gui_python = console_path.with_name('pythonw.exe')
        if gui_python.exists():
            return str(gui_python)
    return str(console_path)


def extract_backend_pid(health):
    pid = str((health or {}).get('backend_process_id') or '').strip()
    return pid if pid.isdigit() else ''


def terminate_pid(pid):
    normalized_pid = str(pid or '').strip()
    if not normalized_pid.isdigit():
        return False
    creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.run(
        ['taskkill', '/PID', normalized_pid, '/T', '/F'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    return True


def terminate_process(process, timeout_seconds=3):
    if process is None or process.poll() is not None:
        return False
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except Exception:
        pass
    if process.poll() is None:
        return terminate_pid(getattr(process, 'pid', ''))
    return False


def get_backend_health(timeout_seconds=2):
    try:
        timeout = max(1, int(timeout_seconds or 0))
        return BackendClient(timeout=timeout).health()
    except Exception:
        return None


def wait_for_backend_release(timeout_seconds=5):
    deadline = time.time() + max(0.5, float(timeout_seconds or 0))
    while time.time() < deadline:
        if get_backend_health(timeout_seconds=1) is None:
            return True
        time.sleep(0.2)
    return get_backend_health(timeout_seconds=1) is None


def is_database_locked():
    try:
        connection = sqlite3.connect(DATABASE_FILE, timeout=1)
        try:
            connection.execute('SELECT 1')
        finally:
            connection.close()
    except sqlite3.OperationalError as exc:
        return 'locked' in str(exc).lower()
    return False


def format_backend_failure(process_alive, stale_backend_cleaned=False):
    if process_alive:
        if stale_backend_cleaned:
            return '检测到旧后端并已尝试清理，但新后端仍未在预期时间内启动。'
        return '后端仍在初始化，可能正在整理较大的数据库。'
    if is_database_locked():
        return '检测到数据库正被占用，可能有旧后端、数据库工具或其他程序尚未释放数据库文件。'
    if stale_backend_cleaned:
        return '检测到旧后端并已尝试清理，但新后端启动失败。'
    return '后端服务启动失败。'


def tail_text(text, max_lines=12):
    lines = [line.rstrip() for line in str(text or '').splitlines() if line.strip()]
    if not lines:
        return ''
    return '\n'.join(lines[-max_lines:])


class StartupLogger:
    def __init__(self, log_file):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def write(self, message):
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        line = f'[{timestamp}] {message}'
        print(line)
        with self.log_file.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')


def start_backend_process(console_python, instance_token):
    backend_script = PROJECT_ROOT / 'backend_server.py'
    creation_flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return subprocess.Popen(
        [str(console_python), str(backend_script), '--instance-token', instance_token],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='ignore',
        creationflags=creation_flags,
    )


def wait_for_expected_backend(instance_token, process, logger, startup_timeout_seconds, stale_backend_cleaned=False):
    deadline = time.time() + max(30.0, float(startup_timeout_seconds or 0))
    while time.time() < deadline:
        if process.poll() is not None:
            stdout_text, stderr_text = process.communicate()
            detail = tail_text(stderr_text) or tail_text(stdout_text) or '后端进程已退出，但没有返回更多错误信息。'
            raise RuntimeError(f'后端进程已退出：\n{detail}')
        health = get_backend_health(timeout_seconds=1)
        if is_expected_backend(health, instance_token):
            logger.write(
                f"后端健康检查通过，PID={extract_backend_pid(health) or getattr(process, 'pid', '')}，端口={get_backend_port()}"
            )
            return
        time.sleep(0.2)

    if process.poll() is None:
        terminate_process(process, timeout_seconds=3)
        wait_for_backend_release(timeout_seconds=3)
    raise RuntimeError(format_backend_failure(process_alive=True, stale_backend_cleaned=stale_backend_cleaned))


def run_launcher(test_mode=False):
    logger = StartupLogger(STARTUP_LOG_FILE)
    console_python = Path(sys.executable).resolve()
    gui_python = choose_gui_interpreter(console_python)

    logger.write(f'项目目录: {PROJECT_ROOT}')
    logger.write(f'控制台解释器: {console_python}')
    logger.write(f'GUI 解释器: {gui_python}')
    logger.write(f'启动日志: {STARTUP_LOG_FILE}')

    if test_mode:
        logger.write(f'后端端口: {get_backend_port()}')
        logger.write(f'后端超时配置: {get_backend_timeout_seconds()} 秒')
        return 0

    stale_backend_cleaned = False
    existing_health = get_backend_health(timeout_seconds=2)
    if existing_health is not None:
        if not is_project_backend(existing_health):
            raise RuntimeError(f'检测到端口 {get_backend_port()} 已被其他进程占用，安全启动器不会接管该进程。')
        existing_pid = extract_backend_pid(existing_health)
        logger.write(f'检测到旧后端，准备清理。PID={existing_pid or "未知"}')
        stale_backend_cleaned = terminate_pid(existing_pid)
        if stale_backend_cleaned:
            wait_for_backend_release(timeout_seconds=5)
        if get_backend_health(timeout_seconds=1) is not None:
            raise RuntimeError('旧后端未能成功退出，请先关闭旧实例后重试。')

    instance_token = uuid.uuid4().hex
    backend_process = None
    gui_process = None
    startup_timeout_seconds = max(30.0, float(get_backend_timeout_seconds() or 0))
    try:
        logger.write('正在启动后端服务...')
        backend_process = start_backend_process(console_python, instance_token)
        wait_for_expected_backend(
            instance_token,
            backend_process,
            logger,
            startup_timeout_seconds=startup_timeout_seconds,
            stale_backend_cleaned=stale_backend_cleaned,
        )

        gui_env = build_gui_environment(os.environ, instance_token, owns_backend=True)
        gui_script = PROJECT_ROOT / 'Local_Video_gui.py'
        logger.write('后端准备完成，正在启动图形界面...')
        gui_process = subprocess.Popen(
            [str(gui_python), str(gui_script)],
            cwd=str(PROJECT_ROOT),
            env=gui_env,
        )
        exit_code = gui_process.wait()
        logger.write(f'图形界面已退出，返回码={exit_code}')
        return int(exit_code or 0)
    finally:
        if backend_process is not None and backend_process.poll() is None:
            logger.write('正在清理安全启动器拉起的后端进程...')
            terminate_process(backend_process, timeout_seconds=3)
            wait_for_backend_release(timeout_seconds=3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    try:
        return run_launcher(test_mode=bool(args.test))
    except Exception as exc:
        logger = StartupLogger(STARTUP_LOG_FILE)
        logger.write(f'启动失败: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

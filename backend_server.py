import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from database_handler import VideoDatabase
from video_renamer_api import (
    VideoRenamerAPI,
    plan_from_dict,
    plan_to_dict,
    result_to_dict,
)


class BackendService:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir or Path(__file__).resolve().parent)
        self.csv_path = self.base_dir / '目录统计 - 详细介绍.csv'
        self.db = VideoDatabase(self.base_dir / 'video_database.db')
        self.renamer = VideoRenamerAPI(self.csv_path)
        self.database_loaded = False

    def load_database(self):
        video_db = self.renamer.load_database()
        self.database_loaded = True
        return {'count': len(video_db), 'csv_path': str(self.csv_path)}

    def ensure_database_loaded(self):
        if not self.database_loaded:
            self.load_database()

    def health(self):
        return {
            'ok': True,
            'database_loaded': self.database_loaded,
            'csv_exists': self.csv_path.exists(),
            'csv_path': str(self.csv_path),
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
        return {'success_count': self.db.save_plans(plans)}

    def list_videos(self, search_text=''):
        return {'videos': self.db.list_videos(search_text)}


def make_handler(service):
    class VideoBackendHandler(BaseHTTPRequestHandler):
        server_version = 'LocalVideoRenamerBackend/1.0'

        def log_message(self, format, *args):
            return

        def do_GET(self):
            self._handle_request('GET')

        def do_POST(self):
            self._handle_request('POST')

        def _handle_request(self, method):
            try:
                parsed_url = urlparse(self.path)
                body = self._read_json_body()
                response = self._route(method, parsed_url, body)
                self._send_json(response)
            except FileNotFoundError as exc:
                self._send_json({'error': str(exc)}, HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({'error': str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._send_json({'error': str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _route(self, method, parsed_url, body):
            path = parsed_url.path.rstrip('/') or '/'
            query = parse_qs(parsed_url.query)

            if method == 'GET' and path == '/health':
                return service.health()
            if method == 'POST' and path == '/database/reload':
                return service.load_database()
            if method == 'POST' and path == '/scan':
                folder_path = body.get('folder_path')
                if not folder_path:
                    raise ValueError('缺少 folder_path')
                return service.scan(folder_path)
            if method == 'POST' and path == '/rename':
                return service.rename(body.get('plans', []))
            if method == 'POST' and path == '/database/save':
                return service.save_plans(body.get('plans', []))
            if method == 'GET' and path == '/database/videos':
                search_text = query.get('q', [''])[0]
                return service.list_videos(search_text)

            raise ValueError(f'未知接口: {method} {path}')

        def _read_json_body(self):
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                return {}

            raw_body = self.rfile.read(content_length).decode('utf-8')
            if not raw_body.strip():
                return {}

            return json.loads(raw_body)

        def _send_json(self, data, status=HTTPStatus.OK):
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return VideoBackendHandler


def run_server(host='127.0.0.1', port=8765):
    service = BackendService()
    server = ThreadingHTTPServer((host, port), make_handler(service))
    print(f'Local Video Renamer backend listening on http://{host}:{port}')
    server.serve_forever()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    run_server(args.host, args.port)

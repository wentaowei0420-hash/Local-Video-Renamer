import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from backend_service import BackendService


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
            if method == 'GET' and path == '/database/actors':
                search_text = query.get('q', [''])[0]
                return service.list_actors(search_text)
            if method == 'GET' and path == '/paths':
                return service.list_paths()
            if method == 'POST' and path == '/paths/add':
                folder_path = body.get('folder_path')
                if not folder_path:
                    raise ValueError('缺少 folder_path')
                return service.add_path(folder_path)
            if method == 'POST' and path == '/paths/delete':
                return service.delete_path(body.get('path_id'))
            if method == 'POST' and path == '/database/enrich':
                return service.enrich_videos(
                    body.get('limit', 1),
                    show_browser=bool(body.get('show_browser')),
                    cooldown_before_search=bool(body.get('cooldown_before_search')),
                )
            if method == 'POST' and path == '/browser-profile/reset':
                return service.reset_browser_profile()

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

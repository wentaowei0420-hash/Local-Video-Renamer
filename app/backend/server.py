import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.backend.service import BackendService
from app.core.runtime_config import get_backend_host, get_backend_port


def make_handler(service):
    def _is_truthy_query_value(query, key):
        return str((query.get(key, [''])[0] or '')).strip().lower() in ('1', 'true', 'yes', 'on')

    def _int_query_value(query, key, default=None):
        raw_value = str((query.get(key, [''])[0] or '')).strip()
        if not raw_value:
            return default
        return int(raw_value)

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
            if method == 'POST' and path == '/database/videos/import':
                return service.import_videos(body.get('plans', []))
            if method == 'GET' and path == '/database/videos':
                search_text = query.get('q', [''])[0]
                return service.list_videos(
                    search_text,
                    sort_field=query.get('sort_field', [''])[0],
                    sort_order=query.get('sort_order', [''])[0],
                    limit=_int_query_value(query, 'limit', default=None),
                    offset=_int_query_value(query, 'offset', default=0),
                )
            if method == 'GET' and path == '/database/videos/summary':
                return service.get_video_enrichment_summary()
            if method == 'GET' and path == '/data-center/summary':
                return service.get_data_center_summary(force_refresh=_is_truthy_query_value(query, 'refresh'))
            if method == 'GET' and path == '/data-center/analysis':
                return service.get_actor_metric_analysis(
                    query.get('metric', [''])[0],
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'POST' and path == '/database/videos/reset':
                return service.reset_video_enrichments(body.get('codes', []), body.get('source_key'))
            if method == 'GET' and path == '/database/videos/manual-category':
                return service.list_videos_requiring_manual_category()
            if method == 'POST' and path == '/database/videos/manual-category/stage':
                return service.stage_video_category(body.get('code'), body.get('category'))
            if method == 'POST' and path == '/database/videos/manual-category/stage/batch':
                return service.stage_video_categories(body.get('entries', []))
            if method == 'POST' and path == '/database/videos/manual-category/sync':
                return service.sync_staged_video_categories()
            if method == 'POST' and path == '/database/videos/category':
                return service.update_video_category(body.get('code'), body.get('category'))
            if method == 'GET' and path == '/database/actors':
                search_text = query.get('q', [''])[0]
                return service.list_actors(
                    search_text,
                    sort_field=query.get('sort_field', [''])[0],
                    sort_order=query.get('sort_order', [''])[0],
                    limit=_int_query_value(query, 'limit', default=None),
                    offset=_int_query_value(query, 'offset', default=0),
                )
            if method == 'GET' and path == '/database/actors/detail':
                actor_name = query.get('name', [''])[0]
                return service.get_actor_detail(actor_name)
            if method == 'POST' and path == '/database/actors/add':
                return service.add_actor(
                    body.get('actor_name'),
                    body.get('birthday', ''),
                    body.get('age', ''),
                )
            if method == 'GET' and path == '/canglangge/candidates':
                return service.list_canglangge_candidates(force_refresh=_is_truthy_query_value(query, 'refresh'))
            if method == 'POST' and path == '/canglangge/admit':
                return service.admit_canglangge_candidates(body.get('actor_names', []))
            if method == 'POST' and path == '/canglangge/delete':
                return service.delete_canglangge_candidates(body.get('actor_names', []))
            if method == 'POST' and path == '/database/actors/reset':
                return service.reset_actor_enrichments(body.get('actor_names', []), body.get('source_key'))
            if method == 'POST' and path == '/database/actors/rename':
                return service.rename_actor(
                    body.get('old_name'),
                    body.get('new_name'),
                    body.get('birthday', ''),
                    body.get('age', ''),
                )
            if method == 'POST' and path == '/database/actors/delete':
                return service.delete_actor(body.get('actor_name'))
            if method == 'GET' and path == '/database/code-prefixes':
                search_text = query.get('q', [''])[0]
                return service.list_code_prefixes(search_text)
            if method == 'GET' and path == '/database/code-prefixes/detail':
                prefix = query.get('prefix', [''])[0]
                return service.get_code_prefix_detail(prefix)
            if method == 'POST' and path == '/database/code-prefixes/add':
                return service.add_code_prefix(body.get('prefix'))
            if method == 'POST' and path == '/database/code-prefixes/detail/category':
                return service.update_code_prefix_uncategorized_video_category(body.get('prefix'), body.get('category'))
            if method == 'POST' and path == '/database/code-prefixes/reset':
                return service.reset_code_prefix_enrichments(body.get('prefixes', []), body.get('source_key'))
            if method == 'POST' and path == '/database/code-prefixes/rename':
                return service.rename_code_prefix(body.get('old_prefix'), body.get('new_prefix'))
            if method == 'POST' and path == '/database/code-prefixes/delete':
                return service.delete_code_prefix(body.get('prefix'))
            if method == 'GET' and path == '/ladder/board':
                return service.get_ladder_board(
                    query.get('board_key', [''])[0],
                    force_refresh=_is_truthy_query_value(query, 'refresh'),
                )
            if method == 'POST' and path == '/ladder/entries/select':
                return service.admit_ladder_entry(body.get('board_key'), body.get('entity_name'), body.get('tier'))
            if method == 'POST' and path == '/ladder/entries/medal':
                return service.update_ladder_entry_medal(body.get('board_key'), body.get('entity_name'), body.get('medal'))
            if method == 'GET' and path == '/paths':
                return service.list_paths(force_refresh=_is_truthy_query_value(query, 'refresh'))
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
                    target_type=body.get('target_type'),
                    source_key=body.get('source_key'),
                )
            if method == 'POST' and path == '/database/enrich/combo':
                return service.enrich_combo(
                    body.get('combo_key'),
                    body.get('limit', 1),
                    show_browser=bool(body.get('show_browser')),
                    cooldown_before_search=bool(body.get('cooldown_before_search')),
                    combo_task_settings=body.get('combo_task_settings', {}),
                    batch_mode=bool(body.get('batch_mode')),
                )
            if method == 'GET' and path == '/database/enrich/progress':
                return service.get_enrichment_progress()
            if method == 'POST' and path == '/database/enrich/cancel':
                return service.cancel_enrichment()
            if method == 'POST' and path == '/login/auto':
                return service.auto_login()
            if method == 'POST' and path == '/browser-profile/reset':
                return service.reset_browser_profile()
            if method == 'POST' and path == '/database/library-status/sync':
                return service.sync_library_statuses()

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


def run_server(host=None, port=None, instance_token=''):
    host = str(host or get_backend_host()).strip() or get_backend_host()
    port = int(port or get_backend_port())
    service = BackendService(instance_token=instance_token)
    server = ThreadingHTTPServer((host, port), make_handler(service))
    print(f'Local Video Renamer backend listening on http://{host}:{port}')
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default=get_backend_host())
    parser.add_argument('--port', type=int, default=get_backend_port())
    parser.add_argument('--instance-token', default='')
    args = parser.parse_args()
    run_server(args.host, args.port, instance_token=args.instance_token)


if __name__ == '__main__':
    main()

from urllib.parse import urlencode

import requests

from app.core.runtime_config import get_backend_base_url, get_backend_timeout_seconds


_DEFAULT_TIMEOUT = object()


class BackendClient:
    def __init__(self, base_url=None, timeout=None):
        resolved_base_url = str(base_url or get_backend_base_url()).strip()
        self.base_url = resolved_base_url.rstrip('/')
        self.timeout = int(timeout or get_backend_timeout_seconds())

    def health(self):
        return self._get('/health')

    def scan_folder(self, folder_path):
        return self._post('/scan', {'folder_path': folder_path})

    def import_videos(self, plans):
        return self._post('/database/videos/import', {'plans': plans})

    def execute_renames(self, plans):
        return self._post('/rename', {'plans': plans})

    def enrich_videos(
        self,
        limit,
        show_browser=False,
        cooldown_before_search=False,
        target_type=None,
        source_key=None,
    ):
        cooldown_seconds = 180 if cooldown_before_search else 0
        if target_type in ('code_prefix_library', 'actor_library'):
            timeout = max(self.timeout, int(limit or 1) * 240 + 60 + cooldown_seconds)
        else:
            timeout = max(self.timeout, int(limit or 1) * 90 + 60 + cooldown_seconds)
        return self._post(
            '/database/enrich',
            {
                'limit': limit,
                'show_browser': show_browser,
                'cooldown_before_search': cooldown_before_search,
                'target_type': target_type,
                'source_key': source_key,
            },
            timeout=timeout,
        )

    def enrich_combo(
        self,
        combo_key,
        limit,
        show_browser=False,
        cooldown_before_search=False,
        combo_task_settings=None,
        batch_mode=False,
    ):
        combo_task_settings = dict(combo_task_settings or {})
        combo_limits = [
            int((task_settings or {}).get('limit', 0) or 0)
            for task_settings in combo_task_settings.values()
            if int((task_settings or {}).get('limit', 0) or 0) > 0
        ]
        effective_limit = max(combo_limits) if combo_limits else int(limit or 1)
        timeout = None if batch_mode else max(self.timeout, effective_limit * 300 + 120)
        effective_cooldown = cooldown_before_search or any(
            bool((task_settings or {}).get('cooldown_before_search'))
            for task_settings in combo_task_settings.values()
        )
        if effective_cooldown and timeout is not None:
            timeout += 180
        return self._post(
            '/database/enrich/combo',
            {
                'combo_key': combo_key,
                'limit': limit,
                'show_browser': show_browser,
                'cooldown_before_search': cooldown_before_search,
                'combo_task_settings': combo_task_settings,
                'batch_mode': batch_mode,
            },
            timeout=timeout,
        )

    def cancel_enrichment(self):
        return self._post('/database/enrich/cancel')

    def auto_login(self):
        timeout = max(self.timeout, 660)
        return self._post('/login/auto', timeout=timeout)

    def reset_browser_profile(self):
        return self._post('/browser-profile/reset')

    def list_videos(self, search_text=''):
        query = ''
        if search_text:
            query = '?' + urlencode({'q': search_text})
        return self._get('/database/videos' + query).get('videos', [])

    def get_video_enrichment_summary(self):
        return self._get('/database/videos/summary').get('summary', {})

    def get_data_center_summary(self):
        return self._get('/data-center/summary').get('summary', {})

    def get_enrichment_progress(self):
        return self._get('/database/enrich/progress').get('progress', {})

    def reset_video_enrichments(self, codes, source_key=None):
        return self._post('/database/videos/reset', {'codes': codes, 'source_key': source_key}).get('reset_count', 0)

    def list_videos_requiring_manual_category(self):
        return self._get('/database/videos/manual-category')

    def stage_video_category(self, code, category):
        return self._post('/database/videos/manual-category/stage', {'code': code, 'category': category})

    def sync_staged_video_categories(self):
        return self._post('/database/videos/manual-category/sync')

    def update_video_category(self, code, category):
        return self._post('/database/videos/category', {'code': code, 'category': category}).get('updated_count', 0)

    def list_actors(self, search_text=''):
        query = ''
        if search_text:
            query = '?' + urlencode({'q': search_text})
        return self._get('/database/actors' + query).get('actors', [])

    def get_actor_detail(self, actor_name):
        query = '?' + urlencode({'name': actor_name})
        return self._get('/database/actors/detail' + query).get('actor', {})

    def reset_actor_enrichments(self, actor_names, source_key=None):
        return self._post('/database/actors/reset', {'actor_names': actor_names, 'source_key': source_key}).get('reset_count', 0)

    def rename_actor(self, old_name, new_name):
        return self._post(
            '/database/actors/rename',
            {'old_name': old_name, 'new_name': new_name},
        ).get('updated_count', 0)

    def delete_actor(self, actor_name):
        return self._post('/database/actors/delete', {'actor_name': actor_name}).get('deleted_count', 0)

    def list_code_prefixes(self, search_text=''):
        query = ''
        if search_text:
            query = '?' + urlencode({'q': search_text})
        return self._get('/database/code-prefixes' + query).get('prefixes', [])

    def get_code_prefix_detail(self, prefix):
        query = '?' + urlencode({'prefix': prefix})
        return self._get('/database/code-prefixes/detail' + query).get('prefix_detail', {})

    def reset_code_prefix_enrichments(self, prefixes, source_key=None):
        return self._post('/database/code-prefixes/reset', {'prefixes': prefixes, 'source_key': source_key}).get('reset_count', 0)

    def rename_code_prefix(self, old_prefix, new_prefix):
        return self._post(
            '/database/code-prefixes/rename',
            {'old_prefix': old_prefix, 'new_prefix': new_prefix},
        ).get('updated_count', 0)

    def delete_code_prefix(self, prefix):
        return self._post('/database/code-prefixes/delete', {'prefix': prefix}).get('deleted_count', 0)

    def get_path_library(self):
        return self._get('/paths')

    def list_paths(self):
        return self.get_path_library().get('paths', [])

    def add_path(self, folder_path):
        return self._post('/paths/add', {'folder_path': folder_path}).get('path')

    def delete_path(self, path_id):
        return self._post('/paths/delete', {'path_id': path_id}).get('deleted_count', 0)

    def _get(self, path, timeout=_DEFAULT_TIMEOUT):
        request_timeout = self.timeout if timeout is _DEFAULT_TIMEOUT else timeout
        response = requests.get(self.base_url + path, timeout=request_timeout)
        return self._parse_response(response)

    def _post(self, path, payload=None, timeout=_DEFAULT_TIMEOUT):
        request_timeout = self.timeout if timeout is _DEFAULT_TIMEOUT else timeout
        response = requests.post(self.base_url + path, json=payload or {}, timeout=request_timeout)
        return self._parse_response(response)

    def _parse_response(self, response):
        try:
            data = response.json()
        except ValueError:
            response.raise_for_status()
            return {}

        if response.status_code >= 400:
            raise RuntimeError(data.get('error', response.text))

        return data

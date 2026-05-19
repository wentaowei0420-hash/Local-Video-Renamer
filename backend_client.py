from urllib.parse import urlencode

import requests


class BackendClient:
    def __init__(self, base_url='http://127.0.0.1:8765', timeout=30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout

    def health(self):
        return self._get('/health')

    def reload_database(self):
        return self._post('/database/reload')

    def scan_folder(self, folder_path):
        return self._post('/scan', {'folder_path': folder_path})

    def execute_renames(self, plans):
        return self._post('/rename', {'plans': plans})

    def save_plans(self, plans):
        return self._post('/database/save', {'plans': plans})

    def enrich_videos(self, limit, show_browser=False, cooldown_before_search=False):
        # Playwright needs time to open the site, search, and parse each movie page.
        cooldown_seconds = 180 if cooldown_before_search else 0
        timeout = max(self.timeout, int(limit or 1) * 90 + 60 + cooldown_seconds)
        return self._post(
            '/database/enrich',
            {
                'limit': limit,
                'show_browser': show_browser,
                'cooldown_before_search': cooldown_before_search,
            },
            timeout=timeout,
        )

    def reset_browser_profile(self):
        return self._post('/browser-profile/reset')

    def list_videos(self, search_text=''):
        query = ''
        if search_text:
            query = '?' + urlencode({'q': search_text})
        return self._get('/database/videos' + query).get('videos', [])

    def list_actors(self, search_text=''):
        query = ''
        if search_text:
            query = '?' + urlencode({'q': search_text})
        return self._get('/database/actors' + query).get('actors', [])

    def get_path_library(self):
        return self._get('/paths')

    def list_paths(self):
        return self.get_path_library().get('paths', [])

    def add_path(self, folder_path):
        return self._post('/paths/add', {'folder_path': folder_path}).get('path')

    def delete_path(self, path_id):
        return self._post('/paths/delete', {'path_id': path_id}).get('deleted_count', 0)

    def _get(self, path, timeout=None):
        response = requests.get(self.base_url + path, timeout=timeout or self.timeout)
        return self._parse_response(response)

    def _post(self, path, payload=None, timeout=None):
        response = requests.post(self.base_url + path, json=payload or {}, timeout=timeout or self.timeout)
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

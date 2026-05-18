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

    def list_paths(self):
        return self._get('/paths').get('paths', [])

    def add_path(self, folder_path):
        return self._post('/paths/add', {'folder_path': folder_path}).get('path')

    def delete_path(self, path_id):
        return self._post('/paths/delete', {'path_id': path_id}).get('deleted_count', 0)

    def _get(self, path):
        response = requests.get(self.base_url + path, timeout=self.timeout)
        return self._parse_response(response)

    def _post(self, path, payload=None):
        response = requests.post(self.base_url + path, json=payload or {}, timeout=self.timeout)
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

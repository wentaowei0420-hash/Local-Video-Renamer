import unittest
from unittest.mock import patch

from app.services.detail_web_link_service import (
    build_actor_detail_web_url,
    build_code_prefix_detail_web_url,
)


class DetailWebLinkServiceTest(unittest.TestCase):
    @patch('app.services.detail_web_link_service.get_avfan_actor_page_url', return_value='https://avfan.example/casts/actor-123')
    @patch('app.services.detail_web_link_service.get_avfan_actor_search_url', return_value='https://avfan.example/search?q=actor')
    def test_actor_prefers_detail_page_when_actor_id_exists(self, mock_search_url, mock_page_url):
        result = build_actor_detail_web_url('演员A', actor_id='actor-123')

        self.assertEqual(result, 'https://avfan.example/casts/actor-123')
        mock_page_url.assert_called_once_with('actor-123')
        mock_search_url.assert_not_called()

    @patch('app.services.detail_web_link_service.get_avfan_actor_page_url', return_value='https://avfan.example/casts/actor-123')
    @patch('app.services.detail_web_link_service.get_avfan_actor_search_url', return_value='https://avfan.example/search?q=actor')
    def test_actor_falls_back_to_search_page_without_actor_id(self, mock_search_url, mock_page_url):
        result = build_actor_detail_web_url('演员A', actor_id='')

        self.assertEqual(result, 'https://avfan.example/search?q=actor')
        mock_search_url.assert_called_once_with('演员A')
        mock_page_url.assert_not_called()

    @patch('app.services.detail_web_link_service.get_avfan_code_prefix_url', return_value='https://avfan.example/series/ipx?page=1')
    def test_code_prefix_uses_first_page(self, mock_prefix_url):
        result = build_code_prefix_detail_web_url('IPX')

        self.assertEqual(result, 'https://avfan.example/series/ipx?page=1')
        mock_prefix_url.assert_called_once_with('IPX', 1)


if __name__ == '__main__':
    unittest.main()

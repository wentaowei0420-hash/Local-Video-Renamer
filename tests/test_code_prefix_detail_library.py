import unittest

from app.services.detail import CodePrefixDetailLibrary


class CodePrefixDetailLibraryTest(unittest.TestCase):
    def test_prefix_detail_includes_local_videos_and_local_count(self):
        class FakeDatabase:
            def get_code_prefix_enrichment_record(self, prefix):
                return {}

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {'tier': 'A'} if entity_name == 'NEM' else {}

            def list_videos(self):
                return [
                    {'code': 'NEM-001', 'title': 'Local 1', 'release_date': '2024-01-01', 'author': 'Actor A'},
                    {'code': 'NEM-002', 'title': 'Local 2', 'release_date': '2024-02-01', 'author': 'Actor B'},
                    {'code': 'ABC-001', 'title': 'Other', 'release_date': '2024-03-01', 'author': 'Actor C'},
                ]

            def list_code_prefix_movies(self, prefix):
                return [
                    {
                        'code': 'NEM-001',
                        'title': 'Web 1',
                        'release_date': '2024-01-01',
                        'author': 'Actor A',
                        'javtxt_release_date': '2024-01-01',
                        'javtxt_enrichment_status': '已补全',
                        'javtxt_movie_id': '1',
                        'javtxt_url': 'https://example.com/1',
                    }
                ]

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = CodePrefixDetailLibrary(FakeDatabase()).get_prefix_detail('NEM')

        self.assertEqual(detail['video_count'], 2)
        self.assertEqual(detail['ladder_tier'], 'A')
        self.assertEqual([row['code'] for row in detail['local_videos']], ['NEM-001', 'NEM-002'])
        self.assertEqual([row['code'] for row in detail['movies']], ['NEM-001'])
        self.assertEqual(detail['update_frequency']['video_count'], 1)
        self.assertEqual(detail['update_frequency']['month_count'], 1)
        self.assertEqual(detail['update_frequency']['videos_per_month'], 1.0)

    def test_prefix_detail_keeps_top_14_actors_by_appearance_count(self):
        class FakeDatabase:
            def get_code_prefix_enrichment_record(self, prefix):
                return {}

            def get_ladder_entry(self, board_key, entity_type, entity_name):
                return {}

            def list_videos(self):
                return []

            def list_code_prefix_movies(self, prefix):
                rows = []
                for index in range(15):
                    actor_name = f'Actor{index:02d}'
                    repeat_count = 20 - index
                    for repeat in range(repeat_count):
                        rows.append(
                            {
                                'code': f'NEM-{index:02d}-{repeat:02d}',
                                'title': f'Web {index:02d}-{repeat:02d}',
                                'release_date': '2024-01-01',
                                'author': actor_name,
                                'javtxt_release_date': '2024-01-01',
                                'javtxt_enrichment_status': '已补全',
                                'javtxt_movie_id': f'{index:02d}-{repeat:02d}',
                                'javtxt_url': f'https://example.com/{index:02d}-{repeat:02d}',
                            }
                        )
                return rows

            def get_javtxt_actor_cache_by_codes(self, codes):
                return {}

        detail = CodePrefixDetailLibrary(FakeDatabase()).get_prefix_detail('NEM')

        self.assertEqual(len(detail['top_actors']), 14)
        self.assertEqual(detail['top_actors'][0]['name'], 'Actor00')
        self.assertEqual(detail['top_actors'][-1]['name'], 'Actor13')


if __name__ == '__main__':
    unittest.main()

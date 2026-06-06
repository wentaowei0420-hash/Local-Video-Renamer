from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core.ladder_board import (
    LADDER_BOARD_ACTOR,
    LADDER_BOARD_CODE_PREFIX,
    normalize_ladder_medal_text,
    split_ladder_medals,
)
from app.data.database_handler import VideoDatabase
from app.services.ladder_board_service import LadderBoardService


class LadderBoardServiceTest(unittest.TestCase):
    def test_medal_text_normalizes_multiple_delimiters(self):
        medal_text = '年度新人，白金常青树\n封面女王；年度新人|传奇系列'

        self.assertEqual(
            split_ladder_medals(medal_text),
            ['年度新人', '白金常青树', '封面女王', '传奇系列'],
        )
        self.assertEqual(
            normalize_ladder_medal_text(medal_text),
            '年度新人\n白金常青树\n封面女王\n传奇系列',
        )

    def test_actor_candidates_fill_top_20_after_selected_entries_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / 'video_database.db'
            db = VideoDatabase(db_path)
            db.import_local_videos(
                [
                    {
                        'code': f'ABP-{index:03d}',
                        'storage_location': 'D:\\videos',
                        'size': '1GB',
                    }
                    for index in range(1, 26)
                ]
            )

            with closing(sqlite3.connect(db_path)) as conn:
                for index in range(1, 26):
                    conn.execute(
                        'UPDATE processed_videos SET author = ? WHERE code = ?',
                        (f'演员{index:02d}', f'ABP-{index:03d}'),
                    )
                conn.commit()

            service = LadderBoardService(db)
            service.admit_entry(LADDER_BOARD_ACTOR, '演员01', 'S')
            service.admit_entry(LADDER_BOARD_ACTOR, '演员02', 'A')
            board = service.get_board(LADDER_BOARD_ACTOR)

        self.assertEqual(len(board['candidates']), 20)
        self.assertEqual(board['candidates'][0]['entity_name'], '演员03')
        self.assertEqual(board['candidates'][-1]['entity_name'], '演员22')
        self.assertEqual([item['entity_name'] for item in board['selected']], ['演员01', '演员02'])

    def test_code_prefix_selected_entries_keep_tier_and_medal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = VideoDatabase(Path(temp_dir) / 'video_database.db')
            db.import_local_videos(
                [
                    {'code': 'IPX-001', 'storage_location': 'D:\\videos', 'size': '1GB'},
                    {'code': 'IPX-002', 'storage_location': 'D:\\videos', 'size': '1GB'},
                    {'code': 'MIDV-001', 'storage_location': 'D:\\videos', 'size': '1GB'},
                ]
            )
            service = LadderBoardService(db)
            service.admit_entry(LADDER_BOARD_CODE_PREFIX, 'IPX', 'S')
            service.update_medal(LADDER_BOARD_CODE_PREFIX, 'IPX', '白金常青树，年度新人')
            board = service.get_board(LADDER_BOARD_CODE_PREFIX)

        self.assertEqual(len(board['selected']), 1)
        self.assertEqual(board['selected'][0]['entity_name'], 'IPX')
        self.assertEqual(board['selected'][0]['tier'], 'S')
        self.assertEqual(board['selected'][0]['medal'], '白金常青树\n年度新人')
        self.assertEqual(board['selected'][0]['medals'], ['白金常青树', '年度新人'])
        self.assertEqual(board['candidates'][0]['entity_name'], 'MIDV')


if __name__ == '__main__':
    unittest.main()

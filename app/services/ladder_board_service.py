from app.core.ladder_board import (
    LADDER_BOARD_CODE_PREFIX,
    LADDER_ENTITY_ACTOR,
    LADDER_ENTITY_CODE_PREFIX,
    get_ladder_board_config,
    ladder_tier_sort_key,
    normalize_ladder_medal_text,
    normalize_ladder_board_key,
    normalize_ladder_tier,
    split_ladder_medals,
)
from app.services.actor_identifier import is_ignored_actor_name, split_actor_names
from app.services.code_prefix_library import extract_code_prefix


class LadderBoardService:
    def __init__(self, database):
        self.database = database

    def get_board(self, board_key):
        config = get_ladder_board_config(board_key)
        local_counts = self._build_local_counts(config['entity_type'])
        selected_entries = self.database.list_ladder_entries(config['board_key'], config['entity_type'])
        selected_names = {
            str((entry or {}).get('entity_name', '') or '').strip()
            for entry in selected_entries
            if str((entry or {}).get('entity_name', '') or '').strip()
        }

        candidates = []
        for entity_name, local_video_count in local_counts:
            if entity_name in selected_names:
                continue
            candidates.append(
                {
                    'entity_name': entity_name,
                    'display_name': entity_name,
                    'local_video_count': int(local_video_count or 0),
                }
            )
            if len(candidates) >= 20:
                break

        selected = []
        for entry in selected_entries:
            entity_name = str((entry or {}).get('entity_name', '') or '').strip()
            medal_text = normalize_ladder_medal_text((entry or {}).get('medal', ''))
            selected.append(
                {
                    'entity_name': entity_name,
                    'display_name': entity_name,
                    'tier': str((entry or {}).get('tier', '') or '').strip().upper(),
                    'medal': medal_text,
                    'medals': split_ladder_medals(medal_text),
                    'local_video_count': int(dict(local_counts).get(entity_name, 0) or 0),
                }
            )

        selected.sort(
            key=lambda item: (
                ladder_tier_sort_key(item.get('tier')),
                -int(item.get('local_video_count', 0) or 0),
                str(item.get('display_name', '') or '').upper(),
            )
        )

        return {
            'board_key': config['board_key'],
            'entity_type': config['entity_type'],
            'candidates': candidates,
            'selected': selected,
        }

    def admit_entry(self, board_key, entity_name, tier):
        config = get_ladder_board_config(board_key)
        normalized_name = str(entity_name or '').strip()
        normalized_tier = normalize_ladder_tier(tier)
        if not normalized_name:
            raise ValueError('缺少入选名称')
        if not normalized_tier:
            raise ValueError('请选择有效等级')

        available_names = {name for name, _count in self._build_local_counts(config['entity_type'])}
        if normalized_name not in available_names:
            raise ValueError('未找到对应候选项')

        self.database.save_ladder_entry(
            config['board_key'],
            config['entity_type'],
            normalized_name,
            normalized_tier,
        )
        return self.get_board(config['board_key'])

    def update_medal(self, board_key, entity_name, medal):
        config = get_ladder_board_config(board_key)
        normalized_name = str(entity_name or '').strip()
        if not normalized_name:
            raise ValueError('缺少入选名称')
        self.database.update_ladder_entry_medal(
            config['board_key'],
            config['entity_type'],
            normalized_name,
            normalize_ladder_medal_text(medal),
        )
        return self.get_board(config['board_key'])

    def _build_local_counts(self, entity_type):
        if entity_type == LADDER_ENTITY_ACTOR:
            return self._build_actor_local_counts()
        if entity_type == LADDER_ENTITY_CODE_PREFIX:
            return self._build_code_prefix_local_counts()
        return []

    def _build_actor_local_counts(self):
        grouped = {}
        for row in self.database.list_videos():
            for actor_name in split_actor_names((row or {}).get('author', '')):
                normalized_name = str(actor_name or '').strip()
                if not normalized_name or is_ignored_actor_name(normalized_name):
                    continue
                grouped[normalized_name] = grouped.get(normalized_name, 0) + 1
        return self._sort_grouped_counts(grouped)

    def _build_code_prefix_local_counts(self):
        grouped = {}
        for row in self.database.list_videos():
            prefix = extract_code_prefix((row or {}).get('code', ''))
            if not prefix:
                continue
            grouped[prefix] = grouped.get(prefix, 0) + 1
        return self._sort_grouped_counts(grouped)

    @staticmethod
    def _sort_grouped_counts(grouped):
        return sorted(
            grouped.items(),
            key=lambda item: (-int(item[1] or 0), str(item[0] or '').upper()),
        )

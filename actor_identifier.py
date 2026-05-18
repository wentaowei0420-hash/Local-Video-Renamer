import csv
import re
from pathlib import Path

from filename_rules import normalize_text_spacing


IGNORED_ACTOR_NAMES = {'无', '暂无', '未知', '无记录', 'none', 'null', 'n/a', 'na', '-'}


class ActorIdentifier:
    def __init__(self, actor_csv_path):
        self.actor_csv_path = Path(actor_csv_path)
        self.actor_profiles = {}

    def load_profiles(self):
        self.actor_profiles = load_actor_profiles(self.actor_csv_path)
        return self.actor_profiles

    def ensure_profiles_loaded(self):
        if not self.actor_profiles:
            self.load_profiles()

    def identify_from_author_text(self, author_text):
        self.ensure_profiles_loaded()

        actors = []
        seen = set()
        for name in split_actor_names(author_text):
            if name in seen:
                continue
            seen.add(name)

            profile = self.actor_profiles.get(name, {})
            actors.append({
                'name': name,
                'birthday': profile.get('birthday', ''),
                'age': profile.get('age', ''),
                'matched': bool(profile),
            })

        return actors

    def identify_from_plans(self, plans):
        actors = []
        seen = set()

        for plan in plans:
            for actor in self.identify_from_author_text(plan.metadata.author):
                name = actor['name']
                if name in seen:
                    continue
                seen.add(name)
                actors.append(actor)

        return actors


def load_actor_profiles(actor_csv_path):
    actor_csv_path = Path(actor_csv_path)
    profiles = {}

    if not actor_csv_path.exists():
        raise FileNotFoundError(f'未找到演员统计 CSV 文件: {actor_csv_path}')

    with actor_csv_path.open(mode='r', encoding='utf-8-sig', errors='ignore', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = normalize_actor_name(row.get('主角', ''))
            if not name or is_ignored_actor_name(name):
                continue

            profiles[name] = {
                'name': name,
                'birthday': normalize_text_spacing(row.get('生日', '')),
                'age': normalize_text_spacing(row.get('年龄', '')),
            }

            alias = normalize_actor_name(row.get('类型', ''))
            if alias and not is_ignored_actor_name(alias) and alias not in profiles:
                profiles[alias] = profiles[name]

    return profiles


def split_actor_names(author_text):
    author_text = normalize_text_spacing(author_text or '')
    if not author_text:
        return []

    # 当前数据中多个演员主要以空格分隔；同时兼容常见中英文分隔符。
    raw_names = re.split(r'[\s,，、/／&＆]+', author_text)
    return [
        name
        for name in (normalize_actor_name(raw_name) for raw_name in raw_names)
        if name and not is_ignored_actor_name(name)
    ]


def normalize_actor_name(name):
    return normalize_text_spacing(name).strip('　 \t\r\n')


def is_ignored_actor_name(name):
    return normalize_actor_name(name).lower() in IGNORED_ACTOR_NAMES

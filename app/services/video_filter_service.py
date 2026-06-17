from app.core.video_filter_rules import (
    normalize_video_filter_settings,
    should_hide_video_from_library,
    should_skip_video_before_enrichment,
)
from app.core.video_filter_settings import load_video_filter_settings


class VideoFilterService:
    def __init__(self, settings_loader=None):
        self.settings_loader = settings_loader or load_video_filter_settings

    def load_settings(self):
        return normalize_video_filter_settings(self.settings_loader())

    def build_pre_enrichment_filter(self, settings=None):
        active_settings = normalize_video_filter_settings(self.load_settings() if settings is None else settings)
        return lambda video: not should_skip_video_before_enrichment(video, active_settings)

    def filter_library_rows(self, rows, settings=None):
        active_settings = normalize_video_filter_settings(self.load_settings() if settings is None else settings)
        return [
            dict(row or {})
            for row in (rows or [])
            if not should_hide_video_from_library(row, active_settings)
        ]

    def filter_video_rows(self, rows, settings=None):
        return self.filter_library_rows(rows, settings=settings)

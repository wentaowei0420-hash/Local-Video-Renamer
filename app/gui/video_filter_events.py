from PyQt5.QtCore import QObject, pyqtSignal


class VideoFilterEventBus(QObject):
    rules_saved = pyqtSignal()


video_filter_event_bus = VideoFilterEventBus()

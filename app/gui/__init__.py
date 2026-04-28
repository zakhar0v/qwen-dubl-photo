"""
GUI модуль для приложения поиска дубликатов фото.
Использует PySide6 для создания интерфейса.
"""

from .main_window import MainWindow
from .worker import ScanWorker
from .image_loader import ImageLoader

__all__ = ['MainWindow', 'ScanWorker', 'ImageLoader']

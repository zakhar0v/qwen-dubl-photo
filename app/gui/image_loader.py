"""
Асинхронный загрузчик изображений с кэшированием.
Реализует ленивую загрузку превью для GUI.
"""

from PyQt6.QtCore import QObject, QThread, QPixmap, QSize
from PyQt6.QtGui import QImage
from PyQt6 import QtCore

# Алиас для совместимости с PySide6
Signal = QtCore.pyqtSignal

from typing import Dict, Optional, Tuple
from PIL import Image
import threading
import os


class ImageLoaderWorker(QThread):
    """Рабочий поток для загрузки отдельного изображения."""
    
    loaded = Signal(str, QPixmap)  # path, pixmap
    failed = Signal(str, str)  # path, error
    
    def __init__(self, file_path: str, size: Tuple[int, int] = (200, 200)):
        super().__init__()
        self.file_path = file_path
        self.size = size
    
    def run(self):
        try:
            if not os.path.exists(self.file_path):
                self.failed.emit(self.file_path, "File not found")
                return
            
            # Открываем изображение через Pillow
            with Image.open(self.file_path) as img:
                # Конвертируем в RGB если нужно
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')
                
                # Создаем превью
                img.thumbnail(self.size, Image.Resampling.LANCZOS)
                
                # Конвертируем в QImage
                qimage = QImage(
                    img.tobytes(),
                    img.width,
                    img.height,
                    QImage.Format_RGB888
                )
                
                pixmap = QPixmap.fromImage(qimage)
                self.loaded.emit(self.file_path, pixmap)
                
        except Exception as e:
            self.failed.emit(self.file_path, str(e))


class ImageCache:
    """Кэш для загруженных изображений."""
    
    def __init__(self, max_size: int = 100):
        self._cache: Dict[str, QPixmap] = {}
        self._max_size = max_size
        self._lock = threading.Lock()
    
    def get(self, path: str) -> Optional[QPixmap]:
        """Получение изображения из кэша."""
        with self._lock:
            return self._cache.get(path)
    
    def put(self, path: str, pixmap: QPixmap):
        """Добавление изображения в кэш."""
        with self._lock:
            # Если кэш полон, удаляем oldest
            if len(self._cache) >= self._max_size:
                # Удаляем первый элемент (oldest)
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            
            self._cache[path] = pixmap
    
    def clear(self):
        """Очистка кэша."""
        with self._lock:
            self._cache.clear()
    
    def remove(self, path: str):
        """Удаление изображения из кэша."""
        with self._lock:
            self._cache.pop(path, None)


class ImageLoader(QObject):
    """
    Менеджер загрузки изображений.
    
    Управляет пулом воркеров и кэшем изображений.
    """
    
    image_loaded = Signal(str, QPixmap)  # path, pixmap
    image_failed = Signal(str, str)  # path, error
    
    def __init__(self, max_workers: int = 4, cache_size: int = 100):
        super().__init__()
        self.cache = ImageCache(cache_size)
        self.max_workers = max_workers
        self._active_workers: Dict[str, ImageLoaderWorker] = {}
        self._lock = threading.Lock()
    
    def load(self, file_path: str, size: Tuple[int, int] = (200, 200)):
        """
        Загрузка изображения.
        
        Если изображение в кэше - отправляем сразу.
        Иначе создаем воркера для загрузки.
        """
        # Проверяем кэш
        cached = self.cache.get(file_path)
        if cached:
            self.image_loaded.emit(file_path, cached)
            return
        
        # Проверяем, не загружается ли уже
        with self._lock:
            if file_path in self._active_workers:
                return  # Уже загружается
        
        # Создаем воркера
        worker = ImageLoaderWorker(file_path, size)
        worker.loaded.connect(self._on_worker_loaded)
        worker.failed.connect(self._on_worker_failed)
        
        with self._lock:
            self._active_workers[file_path] = worker
        
        worker.start()
    
    def _on_worker_loaded(self, path: str, pixmap: QPixmap):
        """Обработка успешной загрузки."""
        # Кэшируем
        self.cache.put(path, pixmap)
        
        # Удаляем из активных
        with self._lock:
            self._active_workers.pop(path, None)
        
        # Отправляем сигнал
        self.image_loaded.emit(path, pixmap)
    
    def _on_worker_failed(self, path: str, error: str):
        """Обработка ошибки загрузки."""
        # Удаляем из активных
        with self._lock:
            self._active_workers.pop(path, None)
        
        # Отправляем сигнал об ошибке
        self.image_failed.emit(path, error)
    
    def cancel(self, file_path: str):
        """Отмена загрузки изображения."""
        with self._lock:
            worker = self._active_workers.pop(file_path, None)
            if worker:
                worker.quit()
                worker.wait()
    
    def clear_cache(self):
        """Очистка кэша изображений."""
        self.cache.clear()
    
    def preload(self, file_paths: list, size: Tuple[int, int] = (200, 200)):
        """Предзагрузка списка изображений."""
        for path in file_paths[:self.max_workers]:
            self.load(path, size)

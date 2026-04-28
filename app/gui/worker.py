"""
Рабочий поток для выполнения сканирования в фоне.
Отправляет сигналы прогресса и результатов в главный поток.
"""

from PyQt6.QtCore import QThread, QObject
from PyQt6 import QtCore

# Алиас для совместимости с PySide6
Signal = QtCore.pyqtSignal

from typing import Optional
import sys
import os

# Добавляем корень проекта в path для импортов
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.core import DuplicateFinder


class ScanWorker(QThread):
    """
    Рабочий поток для выполнения сканирования.
    
    Сигналы:
        progress(current, total, stage) - обновление прогресса
        status(message) - обновление статуса
        finished(result) - завершение сканирования
        error(message) - ошибка
    """
    
    progress = Signal(int, int, str)
    status = Signal(str)
    finished = Signal(dict)
    error = Signal(str)
    
    def __init__(self, directory: str, db_path: str = "duplicates.db"):
        super().__init__()
        self.directory = directory
        self.db_path = db_path
        self.finder: Optional[DuplicateFinder] = None
        self._stopped = False
    
    def run(self):
        """Запуск процесса сканирования."""
        try:
            self._stopped = False
            
            # Создаем экземпляр DuplicateFinder
            self.finder = DuplicateFinder(self.db_path)
            
            # Устанавливаем коллбэки
            self.finder.set_progress_callback(self._on_progress)
            self.finder.set_status_callback(self._on_status)
            
            # Запускаем полное сканирование
            result = self.finder.run_full_scan(self.directory)
            
            # Получаем группы дубликатов
            groups = self.finder.get_duplicate_groups()
            stats = self.finder.get_statistics()
            
            result['groups'] = groups
            result['stats'] = stats
            
            self.finished.emit(result)
            
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.finder:
                self.finder.close()
    
    def _on_progress(self, current: int, total: int, stage: str):
        """Коллбэк прогресса."""
        if not self._stopped:
            self.progress.emit(current, total, stage)
    
    def _on_status(self, message: str):
        """Коллбэк статуса."""
        if not self._stopped:
            self.status.emit(message)
    
    def stop(self):
        """Остановка сканирования."""
        self._stopped = True
        if self.finder:
            self.finder.stop()
        self.quit()
        self.wait()

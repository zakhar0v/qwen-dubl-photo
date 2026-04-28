"""
Модуль сканера файлов для приложения поиска дубликатов.
Реализует сканирование файловой системы и извлечение метаданных.
"""

import os
import mimetypes
from pathlib import Path
from typing import List, Tuple, Optional, Iterator, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import threading


class FileScanner:
    """Сканер файлов для обхода директорий и сбора метаданных."""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._stop_flag = threading.Event()
    
    def stop(self):
        """Остановка сканирования."""
        self._stop_flag.set()
    
    def reset(self):
        """Сброс флага остановки."""
        self._stop_flag.clear()
    
    def scan_directory(self, directory: str) -> Iterator[Dict[str, Any]]:
        """
        Рекурсивное сканирование директории.
        
        Args:
            directory: Путь к директории для сканирования
        
        Yields:
            Словарь с информацией о файле
        """
        directory_path = Path(directory)
        
        if not directory_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        if not directory_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {directory}")
        
        for root, dirs, files in os.walk(directory_path):
            if self._stop_flag.is_set():
                break
            
            # Пропускаем скрытые директории
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            
            for filename in files:
                if self._stop_flag.is_set():
                    break
                
                # Пропускаем скрытые файлы
                if filename.startswith('.'):
                    continue
                
                file_path = Path(root) / filename
                
                try:
                    file_info = self._get_file_info(file_path)
                    if file_info:
                        yield file_info
                except (PermissionError, OSError) as e:
                    # Пропускаем файлы без прав доступа
                    continue
    
    def _get_file_info(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Получение информации о файле.
        
        Args:
            file_path: Путь к файлу
        
        Returns:
            Словарь с информацией о файле или None если файл не подходит
        """
        try:
            stat_info = file_path.stat()
            
            # Проверка размера (пропускаем пустые файлы)
            if stat_info.st_size == 0:
                return None
            
            # Определение MIME-типа
            mime_type, _ = mimetypes.guess_type(str(file_path))
            
            # Фильтрация только изображений
            if mime_type and not mime_type.startswith('image/'):
                # Проверяем расширения для случаев когда mime_type не определен
                ext = file_path.suffix.lower()
                image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', 
                                   '.tif', '.webp', '.raw', '.cr2', '.nef', '.arw', '.dng'}
                if ext not in image_extensions:
                    return None
            
            return {
                'file_path': str(file_path.absolute()),
                'file_name': file_path.name,
                'file_size': stat_info.st_size,
                'mime_type': mime_type or 'application/octet-stream',
                'mtime': stat_info.st_mtime
            }
        except (OSError, PermissionError):
            return None
    
    def scan_files_batch(self, directory: str, batch_size: int = 500) -> Iterator[List[Dict[str, Any]]]:
        """
        Сканирование директории с возвратом результатов порциями.
        
        Args:
            directory: Путь к директории
            batch_size: Размер порции
        
        Yields:
            Список словарей с информацией о файлах
        """
        batch = []
        for file_info in self.scan_directory(directory):
            batch.append(file_info)
            if len(batch) >= batch_size:
                yield batch
                batch = []
        
        if batch:
            yield batch
    
    def prepare_for_db(self, file_info: Dict[str, Any]) -> Tuple[str, str, int, str]:
        """
        Подготовка данных для вставки в БД.
        
        Args:
            file_info: Информация о файле
        
        Returns:
            Кортеж (file_path, file_name, file_size, mime_type)
        """
        return (
            file_info['file_path'],
            file_info['file_name'],
            file_info['file_size'],
            file_info['mime_type']
        )


class FileInfoChecker:
    """Проверка изменений файлов."""
    
    @staticmethod
    def is_file_modified(file_path: str, stored_size: int, stored_mtime: float) -> bool:
        """
        Проверка был ли файл изменен с момента последнего сканирования.
        
        Args:
            file_path: Путь к файлу
            stored_size: Сохраненный размер файла
            stored_mtime: Сохраненное время модификации
        
        Returns:
            True если файл был изменен
        """
        try:
            stat_info = Path(file_path).stat()
            # Проверяем размер и время модификации
            if stat_info.st_size != stored_size:
                return True
            # Сравниваем время с небольшой погрешностью (1 секунда)
            if abs(stat_info.st_mtime - stored_mtime) > 1.0:
                return True
            return False
        except (OSError, PermissionError):
            return True  # Если не можем прочитать, считаем что файл изменен/удален
    
    @staticmethod
    def file_exists(file_path: str) -> bool:
        """Проверка существования файла."""
        try:
            return Path(file_path).exists()
        except (OSError, PermissionError):
            return False

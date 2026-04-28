"""
Менеджер поиска дубликатов.
Координирует работу сканера, EXIF процессора и хешера.
Реализует трехуровневый алгоритм: Имя → EXIF → SHA256.
"""

import threading
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime

from app.db import Database
from app.core import FileScanner, FileInfoChecker, EXIFProcessor, HashCalculator


class DuplicateFinder:
    """Основной класс для поиска дубликатов фотографий."""
    
    def __init__(self, db_path: str = "duplicates.db"):
        self.db = Database(db_path)
        self.scanner = FileScanner()
        self.exif_processor = EXIFProcessor()
        self.hasher = HashCalculator()
        
        self._stop_flag = threading.Event()
        self._progress_callback: Optional[Callable] = None
        self._status_callback: Optional[Callable] = None
    
    def set_progress_callback(self, callback: Callable):
        """Установка коллбэка прогресса."""
        self._progress_callback = callback
    
    def set_status_callback(self, callback: Callable):
        """Установка коллбэка статуса."""
        self._status_callback = callback
    
    def _report_progress(self, current: int, total: int, stage: str = ""):
        """Отчет о прогрессе."""
        if self._progress_callback:
            self._progress_callback(current, total, stage)
    
    def _report_status(self, status: str):
        """Отчет о статусе."""
        if self._status_callback:
            self._status_callback(status)
    
    def stop(self):
        """Остановка процесса поиска."""
        self._stop_flag.set()
        self.scanner.stop()
    
    def reset(self):
        """Сброс флага остановки."""
        self._stop_flag.clear()
        self.scanner.reset()
    
    def scan_directory(self, directory: str) -> int:
        """
        Этап 1: Сканирование директории и заполнение БД.
        
        Args:
            directory: Путь к директории для сканирования
        
        Returns:
            Количество найденных файлов
        """
        self._report_status("Сканирование директории...")
        
        total_files = 0
        batch_count = 0
        
        for batch in self.scanner.scan_files_batch(directory, batch_size=500):
            if self._stop_flag.is_set():
                break
            
            # Подготовка данных для БД
            db_records = []
            for file_info in batch:
                record = self.scanner.prepare_for_db(file_info)
                db_records.append(record)
            
            # Вставка в БД
            inserted = self.db.insert_files_batch(db_records)
            total_files += len(batch)
            batch_count += 1
            
            self._report_progress(total_files, 0, "scan")
        
        self._report_status(f"Найдено файлов: {total_files}")
        return total_files
    
    def check_existing_files(self) -> int:
        """
        Проверка существующих файлов на изменения.
        
        Returns:
            Количество обновленных записей
        """
        self._report_status("Проверка изменений файлов...")
        
        # Получаем все файлы из БД
        cursor = self.db.conn.cursor()
        cursor.execute("""
            SELECT id, file_path, file_size 
            FROM files
            WHERE status IN ('hash_checked', 'duplicate', 'exif_checked')
        """)
        
        updated_count = 0
        batch_ids = []
        
        for row in cursor.fetchall():
            if self._stop_flag.is_set():
                break
            
            file_id, file_path, stored_size = row
            
            # Проверяем существование и изменения
            if not FileInfoChecker.file_exists(file_path):
                # Файл удален - помечаем
                batch_ids.append(file_id)
            else:
                # Проверяем размер (упрощенная проверка)
                try:
                    current_size = FileInfoChecker.__dict__.get('file_exists')
                    import os
                    actual_size = os.path.getsize(file_path)
                    if actual_size != stored_size:
                        batch_ids.append(file_id)
                except:
                    pass
            
            # Пакетное обновление каждые 100 файлов
            if len(batch_ids) >= 100:
                self.db.update_files_status_batch(batch_ids, 'new')
                updated_count += len(batch_ids)
                batch_ids = []
        
        # Обновляем остаток
        if batch_ids:
            self.db.update_files_status_batch(batch_ids, 'new')
            updated_count += len(batch_ids)
        
        self._report_status(f"Обновлено записей: {updated_count}")
        return updated_count
    
    def process_exif(self, file_ids: List[int]) -> int:
        """
        Этап 2: Обработка EXIF данных для указанных файлов.
        
        Args:
            file_ids: Список ID файлов для обработки
        
        Returns:
            Количество обработанных файлов
        """
        processed_count = 0
        
        for file_id in file_ids:
            if self._stop_flag.is_set():
                break
            
            file_info = self.db.get_file_by_id(file_id)
            if not file_info:
                continue
            
            file_path = file_info['file_path']
            
            try:
                exif_data = self.exif_processor.process_file(file_path)
                
                self.db.update_file_status(
                    file_id,
                    'exif_checked',
                    exif_signature=exif_data['exif_signature'],
                    exif_dt_original=exif_data['exif_dt_original'],
                    exif_make=exif_data['exif_make'],
                    exif_model=exif_data['exif_model']
                )
                
                processed_count += 1
                self._report_progress(processed_count, len(file_ids), "exif")
            except Exception as e:
                # Если ошибка EXIF, все равно помечаем как проверенный
                self.db.update_file_status(file_id, 'exif_checked')
                processed_count += 1
        
        return processed_count
    
    def process_hashes(self, file_ids: List[int]) -> int:
        """
        Этап 3: Вычисление SHA256 для указанных файлов.
        
        Args:
            file_ids: Список ID файлов для хеширования
        
        Returns:
            Количество обработанных файлов
        """
        processed_count = 0
        
        for file_id in file_ids:
            if self._stop_flag.is_set():
                break
            
            file_info = self.db.get_file_by_id(file_id)
            if not file_info:
                continue
            
            file_path = file_info['file_path']
            sha256 = self.hasher.calculate_sha256(file_path)
            
            if sha256:
                self.db.update_file_status(file_id, 'hash_checked', sha256=sha256)
            else:
                # Ошибка хеширования - помечаем статус
                self.db.update_file_status(file_id, 'error')
            
            processed_count += 1
            self._report_progress(processed_count, len(file_ids), "hash")
        
        return processed_count
    
    def find_duplicates_by_name(self) -> int:
        """
        Поиск дубликатов по имени файла.
        
        Returns:
            Количество найденных групп
        """
        self._report_status("Поиск дубликатов по имени...")
        
        groups = self.db.find_duplicate_names()
        
        for name, file_ids in groups:
            if self._stop_flag.is_set():
                break
            
            # Для совпадений по имени переходим к EXIF
            self.process_exif(file_ids)
        
        return len(groups)
    
    def find_duplicates_by_exif(self) -> int:
        """
        Поиск дубликатов по EXIF сигнатуре.
        
        Returns:
            Количество найденных групп
        """
        self._report_status("Поиск дубликатов по EXIF...")
        
        groups = self.db.find_duplicate_exif()
        
        for signature, file_ids in groups:
            if self._stop_flag.is_set():
                break
            
            # Для совпадений по EXIF переходим к SHA256
            self.process_hashes(file_ids)
        
        # Также хешируем файлы без EXIF совпадений
        remaining = self.db.get_files_for_hashing(limit=10000)
        if remaining:
            file_ids = [f['id'] for f in remaining]
            self.process_hashes(file_ids)
        
        return len(groups)
    
    def find_duplicates_by_sha256(self) -> int:
        """
        Поиск дубликатов по SHA256 хешу.
        
        Returns:
            Количество найденных групп
        """
        self._report_status("Поиск дубликатов по SHA256...")
        
        groups = self.db.find_duplicate_sha256()
        
        created_groups = 0
        for sha256, file_ids in groups:
            if self._stop_flag.is_set():
                break
            
            self.db.create_duplicate_group('sha256', sha256, file_ids)
            created_groups += 1
        
        return created_groups
    
    def run_full_scan(self, directory: str) -> Dict[str, Any]:
        """
        Полный цикл поиска дубликатов.
        
        Args:
            directory: Путь к директории для сканирования
        
        Returns:
            Статистика результатов
        """
        self.reset()
        start_time = datetime.now()
        
        try:
            # Этап 1: Сканирование
            total_files = self.scan_directory(directory)
            
            if self._stop_flag.is_set():
                return self._get_results(start_time, "interrupted")
            
            # Этап 2: Поиск по именам -> EXIF
            name_groups = self.find_duplicates_by_name()
            
            if self._stop_flag.is_set():
                return self._get_results(start_time, "interrupted")
            
            # Этап 3: Поиск по EXIF -> SHA256
            exif_groups = self.find_duplicates_by_exif()
            
            if self._stop_flag.is_set():
                return self._get_results(start_time, "interrupted")
            
            # Этап 4: Поиск по SHA256
            sha256_groups = self.find_duplicates_by_sha256()
            
            stats = self.db.get_statistics()
            
            return self._get_results(start_time, "completed", **stats)
            
        except Exception as e:
            self._report_status(f"Ошибка: {str(e)}")
            return self._get_results(start_time, "error", error=str(e))
    
    def _get_results(self, start_time: datetime, status: str, **kwargs) -> Dict[str, Any]:
        """Формирование результатов."""
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        return {
            'status': status,
            'duration_seconds': duration,
            'timestamp': end_time.isoformat(),
            **kwargs
        }
    
    def get_duplicate_groups(self) -> List[Dict[str, Any]]:
        """Получение всех групп дубликатов."""
        return self.db.get_duplicate_groups()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Получение статистики БД."""
        return self.db.get_statistics()
    
    def clear_database(self):
        """Очистка базы данных."""
        self.db.clear_database()
    
    def close(self):
        """Закрытие соединения с БД."""
        self.db.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

"""
Модуль вычисления хешей файлов.
Реализует порционное чтение и вычисление SHA256.
"""

import hashlib
from pathlib import Path
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from queue import Queue, Empty


class HashCalculator:
    """Калькулятор хешей файлов с порционным чтением."""
    
    DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1MB chunks
    
    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self.chunk_size = chunk_size
    
    def calculate_sha256(self, file_path: str) -> Optional[str]:
        """
        Вычисление SHA256 хеша файла с порционным чтением.
        
        Args:
            file_path: Путь к файлу
        
        Returns:
            SHA256 хеш в hex формате или None если ошибка
        """
        try:
            sha256_hash = hashlib.sha256()
            
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(self.chunk_size)
                    if not chunk:
                        break
                    sha256_hash.update(chunk)
            
            return sha256_hash.hexdigest()
        except (IOError, OSError, PermissionError):
            return None
    
    def calculate_sha256_with_progress(self, file_path: str, 
                                        callback=None) -> Optional[str]:
        """
        Вычисление SHA256 с коллбэком прогресса.
        
        Args:
            file_path: Путь к файлу
            callback: Функция обратного вызова(current_bytes, total_bytes)
        
        Returns:
            SHA256 хеш или None
        """
        try:
            file_size = Path(file_path).stat().st_size
            sha256_hash = hashlib.sha256()
            processed = 0
            
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(self.chunk_size)
                    if not chunk:
                        break
                    sha256_hash.update(chunk)
                    processed += len(chunk)
                    
                    if callback:
                        callback(processed, file_size)
            
            return sha256_hash.hexdigest()
        except (IOError, OSError, PermissionError):
            return None


class HashWorker:
    """Воркер для асинхронного вычисления хешей."""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._stop_flag = threading.Event()
    
    def stop(self):
        """Остановка воркера."""
        self._stop_flag.set()
        self.executor.shutdown(wait=False)
    
    def hash_file(self, file_path: str) -> Tuple[str, Optional[str]]:
        """
        Вычисление хеша файла (может быть вызвано в потоке).
        
        Args:
            file_path: Путь к файлу
        
        Returns:
            Кортеж (file_path, sha256_hash)
        """
        calculator = HashCalculator()
        hash_result = calculator.calculate_sha256(file_path)
        return (file_path, hash_result)
    
    def hash_files_batch(self, file_paths: list) -> list:
        """
        Пакетное вычисление хешей для списка файлов.
        
        Args:
            file_paths: Список путей к файлам
        
        Returns:
            Список кортежей (file_path, sha256_hash)
        """
        results = []
        futures = {}
        
        for file_path in file_paths:
            if self._stop_flag.is_set():
                break
            future = self.executor.submit(self.hash_file, file_path)
            futures[future] = file_path
        
        for future in as_completed(futures):
            if self._stop_flag.is_set():
                break
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                file_path = futures[future]
                results.append((file_path, None))
        
        return results


class HashPipeline:
    """Конвейер для поточного вычисления хешей."""
    
    def __init__(self, max_workers: int = 4, queue_size: int = 100):
        self.max_workers = max_workers
        self.queue_size = queue_size
        self.task_queue = Queue(maxsize=queue_size)
        self.result_queue = Queue()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._stop_flag = threading.Event()
        self._workers = []
    
    def start(self):
        """Запуск воркеров конвейера."""
        for _ in range(self.max_workers):
            worker = threading.Thread(target=self._worker_loop, daemon=True)
            worker.start()
            self._workers.append(worker)
    
    def stop(self):
        """Остановка конвейера."""
        self._stop_flag.set()
        # Добавляем sentinel значения для остановки воркеров
        for _ in range(self.max_workers):
            try:
                self.task_queue.put_nowait(None)
            except:
                pass
        self.executor.shutdown(wait=False)
    
    def add_task(self, file_id: int, file_path: str):
        """Добавление задачи на вычисление хеша."""
        if not self._stop_flag.is_set():
            self.task_queue.put((file_id, file_path))
    
    def _worker_loop(self):
        """Цикл работы воркера."""
        calculator = HashCalculator()
        
        while not self._stop_flag.is_set():
            try:
                task = self.task_queue.get(timeout=1.0)
                if task is None:  # Sentinel value
                    break
                
                file_id, file_path = task
                hash_result = calculator.calculate_sha256(file_path)
                self.result_queue.put((file_id, file_path, hash_result))
            except Empty:
                continue
            except Exception as e:
                # В случае ошибки отправляем None результат
                if 'task' in locals() and task:
                    file_id, file_path = task
                    self.result_queue.put((file_id, file_path, None))
    
    def get_results(self, timeout: float = 0.1):
        """Получение результатов из очереди."""
        results = []
        while not self.result_queue.empty():
            try:
                result = self.result_queue.get_nowait()
                results.append(result)
            except Empty:
                break
        return results

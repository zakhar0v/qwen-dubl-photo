"""
Модуль базы данных для приложения поиска дубликатов фото.
Реализует схему БД, транзакции и оптимизированные операции.
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any
from contextlib import contextmanager

DB_SCHEMA_VERSION = 1


class Database:
    """Класс для управления SQLite базой данных."""
    
    def __init__(self, db_path: str = "duplicates.db"):
        self.db_path = Path(db_path)
        self.conn: Optional[sqlite3.Connection] = None
        self._initialize_db()
    
    def _initialize_db(self):
        """Инициализация базы данных с оптимизациями."""
        self.conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            isolation_level=None  # Autocommit mode, мы будем управлять транзакциями вручную
        )
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")
        self.conn.execute("PRAGMA cache_size = -64000;")  # 64MB cache
        self.conn.execute("PRAGMA temp_store = MEMORY;")
        self._create_tables()
    
    def _create_tables(self):
        """Создание таблиц согласно спецификации."""
        cursor = self.conn.cursor()
        
        # Таблица files
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                file_name TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                mime_type TEXT,
                sha256 TEXT,
                exif_signature TEXT,
                exif_dt_original TEXT,
                exif_make TEXT,
                exif_model TEXT,
                status TEXT DEFAULT 'new'
            );
        """)
        
        # Индексы для таблицы files
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_file_name ON files(file_name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_file_size ON files(file_size);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_mime_type ON files(mime_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_exif_signature ON files(exif_signature);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_exif_dt_original ON files(exif_dt_original);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_exif_make ON files(exif_make);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_exif_model ON files(exif_model);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);")
        
        # Таблица duplicate_groups
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS duplicate_groups (
                group_id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_type TEXT NOT NULL,
                signature TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Таблица group_files (связующая таблица)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_files (
                group_id INTEGER NOT NULL,
                file_id INTEGER NOT NULL,
                FOREIGN KEY (group_id) REFERENCES duplicate_groups(group_id),
                FOREIGN KEY (file_id) REFERENCES files(id),
                PRIMARY KEY (group_id, file_id)
            );
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_files_group_id ON group_files(group_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_files_file_id ON group_files(file_id);")
        
        self.conn.commit()
    
    @contextmanager
    def transaction(self):
        """Контекстный менеджер для транзакций."""
        try:
            self.conn.execute("BEGIN TRANSACTION;")
            yield self.conn
            self.conn.execute("COMMIT;")
        except Exception as e:
            self.conn.execute("ROLLBACK;")
            raise e
    
    def insert_files_batch(self, files: List[Tuple[str, str, int, str]]) -> int:
        """
        Пакетная вставка файлов в базу данных.
        
        Args:
            files: Список кортежей (file_path, file_name, file_size, mime_type)
        
        Returns:
            Количество вставленных записей
        """
        inserted_count = 0
        with self.transaction():
            cursor = self.conn.cursor()
            for file_path, file_name, file_size, mime_type in files:
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO files (file_path, file_name, file_size, mime_type, status)
                        VALUES (?, ?, ?, ?, 'new')
                    """, (file_path, file_name, file_size, mime_type))
                    if cursor.rowcount > 0:
                        inserted_count += 1
                except sqlite3.IntegrityError:
                    pass  # Файл уже существует
        return inserted_count
    
    def update_file_status(self, file_id: int, status: str, **kwargs):
        """Обновление статуса файла и дополнительных полей."""
        cursor = self.conn.cursor()
        set_clauses = ["status = ?"]
        values = [status]
        
        for key, value in kwargs.items():
            if value is not None:
                set_clauses.append(f"{key} = ?")
                values.append(value)
        
        query = f"UPDATE files SET {', '.join(set_clauses)} WHERE id = ?"
        values.append(file_id)
        cursor.execute(query, tuple(values))
        self.conn.commit()
    
    def update_files_status_batch(self, file_ids: List[int], status: str, **kwargs):
        """Пакетное обновление статуса файлов."""
        if not file_ids:
            return
        
        with self.transaction():
            cursor = self.conn.cursor()
            set_clauses = ["status = ?"]
            values = [status]
            
            for key, value in kwargs.items():
                if value is not None:
                    set_clauses.append(f"{key} = ?")
                    values.append(value)
            
            placeholders = ','.join('?' * len(file_ids))
            query = f"UPDATE files SET {', '.join(set_clauses)} WHERE id IN ({placeholders})"
            values.extend(file_ids)
            cursor.execute(query, tuple(values))
    
    def get_new_files(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Получение файлов со статусом 'new'."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, file_path, file_name, file_size, mime_type
            FROM files
            WHERE status = 'new'
            LIMIT ?
        """, (limit,))
        
        columns = ['id', 'file_path', 'file_name', 'file_size', 'mime_type']
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_files_for_hashing(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Получение файлов для вычисления хеша (статус 'exif_checked' или 'new')."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, file_path, file_name, file_size
            FROM files
            WHERE status IN ('new', 'exif_checked') AND sha256 IS NULL
            LIMIT ?
        """, (limit,))
        
        columns = ['id', 'file_path', 'file_name', 'file_size']
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def find_duplicate_names(self) -> List[Tuple[str, List[int]]]:
        """Поиск групп файлов с одинаковыми именами."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT file_name, GROUP_CONCAT(id) as ids
            FROM files
            WHERE status = 'new'
            GROUP BY file_name
            HAVING COUNT(*) > 1
        """)
        
        results = []
        for row in cursor.fetchall():
            file_name = row[0]
            ids = [int(x) for x in row[1].split(',')]
            results.append((file_name, ids))
        return results
    
    def find_duplicate_exif(self) -> List[Tuple[str, List[int]]]:
        """Поиск групп файлов с одинаковой EXIF сигнатурой."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT exif_signature, GROUP_CONCAT(id) as ids
            FROM files
            WHERE status = 'exif_checked' AND exif_signature IS NOT NULL
            GROUP BY exif_signature
            HAVING COUNT(*) > 1
        """)
        
        results = []
        for row in cursor.fetchall():
            signature = row[0]
            ids = [int(x) for x in row[1].split(',')]
            results.append((signature, ids))
        return results
    
    def find_duplicate_sha256(self) -> List[Tuple[str, List[int]]]:
        """Поиск групп файлов с одинаковым SHA256 хешем."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT sha256, GROUP_CONCAT(id) as ids
            FROM files
            WHERE sha256 IS NOT NULL AND status = 'hash_checked'
            GROUP BY sha256
            HAVING COUNT(*) > 1
        """)
        
        results = []
        for row in cursor.fetchall():
            sha256 = row[0]
            ids = [int(x) for x in row[1].split(',')]
            results.append((sha256, ids))
        return results
    
    def create_duplicate_group(self, match_type: str, signature: str, file_ids: List[int]) -> int:
        """Создание группы дубликатов и связывание файлов."""
        cursor = self.conn.cursor()
        
        # Создаем группу
        cursor.execute("""
            INSERT INTO duplicate_groups (match_type, signature, created_at)
            VALUES (?, ?, ?)
        """, (match_type, signature, datetime.now().isoformat()))
        
        group_id = cursor.lastrowid
        
        # Связываем файлы с группой
        for file_id in file_ids:
            cursor.execute("""
                INSERT INTO group_files (group_id, file_id)
                VALUES (?, ?)
            """, (group_id, file_id))
        
        # Обновляем статус файлов
        placeholders = ','.join('?' * len(file_ids))
        cursor.execute(f"""
            UPDATE files SET status = 'duplicate' WHERE id IN ({placeholders})
        """, tuple(file_ids))
        
        self.conn.commit()
        return group_id
    
    def get_file_by_id(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Получение информации о файле по ID."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, file_path, file_name, file_size, mime_type, sha256,
                   exif_signature, exif_dt_original, exif_make, exif_model, status
            FROM files
            WHERE id = ?
        """, (file_id,))
        
        row = cursor.fetchone()
        if row:
            columns = ['id', 'file_path', 'file_name', 'file_size', 'mime_type', 
                      'sha256', 'exif_signature', 'exif_dt_original', 
                      'exif_make', 'exif_model', 'status']
            return dict(zip(columns, row))
        return None
    
    def get_duplicate_groups(self) -> List[Dict[str, Any]]:
        """Получение всех групп дубликатов с информацией о файлах."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT dg.group_id, dg.match_type, dg.signature, dg.created_at,
                   GROUP_CONCAT(f.file_path) as file_paths,
                   GROUP_CONCAT(f.id) as file_ids
            FROM duplicate_groups dg
            JOIN group_files gf ON dg.group_id = gf.group_id
            JOIN files f ON gf.file_id = f.id
            GROUP BY dg.group_id
        """)
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'group_id': row[0],
                'match_type': row[1],
                'signature': row[2],
                'created_at': row[3],
                'file_paths': row[4].split(','),
                'file_ids': [int(x) for x in row[5].split(',')]
            })
        return results
    
    def get_statistics(self) -> Dict[str, int]:
        """Получение статистики по базе данных."""
        cursor = self.conn.cursor()
        
        stats = {}
        
        cursor.execute("SELECT COUNT(*) FROM files")
        stats['total_files'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM files WHERE status = 'new'")
        stats['new_files'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM files WHERE status = 'duplicate'")
        stats['duplicate_files'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM duplicate_groups")
        stats['duplicate_groups'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(file_size) FROM files")
        result = cursor.fetchone()[0]
        stats['total_size'] = result if result else 0
        
        return stats
    
    def clear_database(self):
        """Очистка всех таблиц базы данных."""
        with self.transaction():
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM group_files;")
            cursor.execute("DELETE FROM duplicate_groups;")
            cursor.execute("DELETE FROM files;")
    
    def close(self):
        """Закрытие соединения с базой данных."""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

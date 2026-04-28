#!/usr/bin/env python3
"""
CLI утилита для поиска дубликатов фотографий.
Использует трехуровневый алгоритм: Имя → EXIF → SHA256.
"""

import argparse
import sys
import os
from datetime import datetime

from app.core import DuplicateFinder


def format_size(size_bytes: int) -> str:
    """Форматирование размера в человекочитаемый вид."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


def main():
    parser = argparse.ArgumentParser(
        description='Поиск дубликатов фотографий с использованием трехуровневого алгоритма (Имя → EXIF → SHA256)'
    )
    parser.add_argument(
        'directory',
        nargs='?',
        default='.',
        help='Директория для сканирования (по умолчанию: текущая)'
    )
    parser.add_argument(
        '-o', '--output',
        default='duplicates.db',
        help='Путь к файлу базы данных (по умолчанию: duplicates.db)'
    )
    parser.add_argument(
        '--clear',
        action='store_true',
        help='Очистить базу данных перед сканированием'
    )
    parser.add_argument(
        '--stats-only',
        action='store_true',
        help='Показать только статистику без сканирования'
    )
    parser.add_argument(
        '--clear-db',
        action='store_true',
        help='Очистить базу данных и выйти'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Подробный вывод'
    )
    
    args = parser.parse_args()
    
    # Проверка директории
    if not os.path.isdir(args.directory):
        print(f"Ошибка: Директория '{args.directory}' не найдена")
        sys.exit(1)
    
    finder = DuplicateFinder(args.output)
    
    try:
        # Очистка БД если запрошено
        if args.clear_db:
            confirm = input("Вы уверены, что хотите очистить базу данных? [y/N]: ")
            if confirm.lower() == 'y':
                finder.clear_database()
                print("База данных очищена.")
            else:
                print("Отменено.")
            return
        
        # Показ статистики
        if args.stats_only:
            stats = finder.get_statistics()
            print("\n=== Статистика базы данных ===")
            print(f"Всего файлов: {stats['total_files']}")
            print(f"Новых файлов: {stats['new_files']}")
            print(f"Дубликатов: {stats['duplicate_files']}")
            print(f"Групп дубликатов: {stats['duplicate_groups']}")
            print(f"Общий размер: {format_size(stats['total_size'])}")
            return
        
        # Очистка перед сканированием
        if args.clear:
            finder.clear_database()
            print("База данных очищена перед сканированием.")
        
        # Коллбэки для вывода прогресса
        last_progress_time = datetime.now()
        
        def on_progress(current, total, stage):
            nonlocal last_progress_time
            now = datetime.now()
            # Обновляем прогресс не чаще 10 раз в секунду
            if (now - last_progress_time).total_seconds() >= 0.1 or args.verbose:
                stage_names = {
                    'scan': 'Сканирование',
                    'exif': 'Обработка EXIF',
                    'hash': 'Вычисление хешей'
                }
                stage_name = stage_names.get(stage, stage)
                if total > 0:
                    percent = (current / total) * 100
                    print(f"\r{stage_name}: {current}/{total} ({percent:.1f}%)", end='', flush=True)
                else:
                    print(f"\r{stage_name}: {current}", end='', flush=True)
                last_progress_time = now
        
        def on_status(status):
            print(f"\n{status}")
        
        finder.set_progress_callback(on_progress)
        finder.set_status_callback(on_status)
        
        # Запуск сканирования
        print(f"\n=== Сканирование: {os.path.abspath(args.directory)} ===")
        result = finder.run_full_scan(args.directory)
        
        # Вывод результатов
        print("\n\n=== Результаты ===")
        print(f"Статус: {result['status']}")
        print(f"Время выполнения: {result['duration_seconds']:.2f} сек")
        
        if result['status'] == 'completed':
            print(f"Всего файлов: {result.get('total_files', 0)}")
            print(f"Найдено дубликатов: {result.get('duplicate_files', 0)}")
            print(f"Групп дубликатов: {result.get('duplicate_groups', 0)}")
            
            # Показ групп дубликатов
            groups = finder.get_duplicate_groups()
            if groups:
                print("\n=== Группы дубликатов ===")
                for i, group in enumerate(groups, 1):
                    print(f"\nГруппа #{i} (совпадение по {group['match_type']}):")
                    for path in group['file_paths']:
                        print(f"  • {path}")
        elif result['status'] == 'error':
            print(f"Ошибка: {result.get('error', 'Неизвестная ошибка')}")
        
    finally:
        finder.close()


if __name__ == '__main__':
    main()

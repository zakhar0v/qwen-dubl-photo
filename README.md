# Photo Duplicate Finder

Приложение для поиска дубликатов фотографий с использованием трехуровневого алгоритма: **Имя → EXIF → SHA256**.

## Возможности

- **Трехуровневый алгоритм поиска:**
  1. Быстрый отсев по имени файла
  2. Сравнение EXIF метаданных
  3. Точное сравнение по SHA256 хешу

- **Оптимизированная работа с БД:**
  - SQLite с WAL режимом
  - Пакетные транзакции для высокой производительности
  - Индексы для быстрого поиска

- **Конвейерная обработка:**
  - Порционное чтение файлов (1MB chunks)
  - Низкое потребление памяти
  - Поддержка прерывания сканирования

## Установка

```bash
pip install Pillow
```

## Использование

### CLI версия

```bash
# Сканирование директории
python -m app.cli /path/to/photos

# Сканирование с подробным выводом
python -m app.cli /path/to/photos -v

# Показать статистику без сканирования
python -m app.cli --stats-only

# Очистить базу и начать заново
python -m app.cli /path/to/photos --clear

# Использовать свой файл БД
python -m app.cli /path/to/photos -o my_duplicates.db
```

### API

```python
from app.core import DuplicateFinder

finder = DuplicateFinder('duplicates.db')

# Коллбэки для прогресса
def on_progress(current, total, stage):
    print(f'{stage}: {current}/{total}')

def on_status(status):
    print(f'Статус: {status}')

finder.set_progress_callback(on_progress)
finder.set_status_callback(on_status)

# Запуск полного сканирования
result = finder.run_full_scan('/path/to/photos')

# Получение результатов
groups = finder.get_duplicate_groups()
for group in groups:
    print(f"Группа {group['group_id']} ({group['match_type']}):")
    for path in group['file_paths']:
        print(f"  - {path}")

finder.close()
```

## Архитектура

```
app/
├── __init__.py           # Основной модуль
├── cli.py                # CLI интерфейс
├── db/
│   ├── __init__.py
│   └── database.py       # SQLite БД, транзакции, индексы
├── core/
│   ├── __init__.py
│   ├── scanner.py        # Сканирование файловой системы
│   ├── exif_processor.py # Обработка EXIF данных
│   ├── hasher.py         # Вычисление SHA256
│   └── duplicate_finder.py # Координатор процесса
└── gui/                  # GUI модуль (в разработке)
```

## Алгоритм работы

1. **Сканирование:** Обход директории, сбор метаданных ФС, вставка в БД
2. **Поиск по имени:** Группировка файлов с одинаковыми именами
3. **Обработка EXIF:** Извлечение метаданных для кандидатов
4. **Поиск по EXIF:** Группировка по сигнатуре EXIF
5. **Вычисление SHA256:** Для всех файлов-кандидатов
6. **Финальный поиск:** Создание групп точных дубликатов

## Производительность

- Обработка ~1000 файлов/сек (SSD, локальные файлы)
- Потребление памяти <100MB при сканировании
- Поддержка прерывания и возобновления

## Лицензия

MIT

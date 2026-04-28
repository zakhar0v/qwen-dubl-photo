"""Основной модуль приложения."""
from app.db import Database
from app.core import (
    FileScanner,
    FileInfoChecker,
    EXIFProcessor,
    HashCalculator,
    HashWorker,
    HashPipeline,
    DuplicateFinder
)

__version__ = "1.0.0"
__all__ = [
    'Database',
    'FileScanner',
    'FileInfoChecker',
    'EXIFProcessor',
    'HashCalculator',
    'HashWorker',
    'HashPipeline',
    'DuplicateFinder'
]

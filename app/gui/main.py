#!/usr/bin/env python3
"""
Точка входа для GUI приложения поиска дубликатов фото.
"""

import sys
import os

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from app.gui.main_window import MainWindow


def main():
    """Запуск GUI приложения."""
    # Включаем поддержку High DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    app = QApplication(sys.argv)
    app.setApplicationName("Photo Duplicate Finder")
    app.setOrganizationName("PhotoTools")
    
    # Создаем главное окно
    window = MainWindow(db_path="duplicates.db")
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

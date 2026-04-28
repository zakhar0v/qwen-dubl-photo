"""
Главное окно приложения.
Реализует 4 зоны: Toolbar, Sidebar, Main View, Properties.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QProgressBar, QStatusBar, QToolBar,
    QFileDialog, QMessageBox, QTabWidget, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QTreeView, QAbstractItemView,
    QScrollArea, QFrame, QGridLayout, QSizePolicy, QDialog,
    QDialogButtonBox, QListWidget, QListWidgetItem, QMenu,
    QApplication
)
from PyQt6.QtCore import Qt, QSize, QThread
from PyQt6.QtGui import QPixmap, QIcon, QAction
from PyQt6 import QtCore

# Алиасы для совместимости с PySide6
Signal = QtCore.pyqtSignal
Slot = QtCore.pyqtSlot

import sys
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.gui.worker import ScanWorker
from app.gui.image_loader import ImageLoader


class PropertiesPanel(QTabWidget):
    """Нижняя панель информации (Зона Г)."""
    
    def __init__(self):
        super().__init__()
        self._setup_ui()
    
    def _setup_ui(self):
        # Вкладка EXIF
        self.exif_widget = QWidget()
        exif_layout = QVBoxLayout(self.exif_widget)
        self.exif_table = QTableWidget()
        self.exif_table.setColumnCount(2)
        self.exif_table.setHorizontalHeaderLabels(["Свойство", "Значение"])
        self.exif_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.exif_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        exif_layout.addWidget(self.exif_table)
        
        # Вкладка Логи
        self.log_widget = QWidget()
        log_layout = QVBoxLayout(self.log_widget)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFontFamily("Consolas")
        log_layout.addWidget(self.log_text)
        
        # Вкладка Инфо о БД
        self.info_widget = QWidget()
        info_layout = QVBoxLayout(self.info_widget)
        self.info_label = QLabel("Нет данных")
        self.info_label.setWordWrap(True)
        info_layout.addWidget(self.info_label)
        
        self.addTab(self.exif_widget, "EXIF Данные")
        self.addTab(self.log_widget, "Лог операций")
        self.addTab(self.info_widget, "Инфо о БД")
    
    def set_exif_data(self, exif_data: Dict[str, Any]):
        """Установка EXIF данных."""
        self.exif_table.setRowCount(0)
        if not exif_data:
            return
        
        for key, value in exif_data.items():
            row = self.exif_table.rowCount()
            self.exif_table.insertRow(row)
            self.exif_table.setItem(row, 0, QTableWidgetItem(str(key)))
            self.exif_table.setItem(row, 1, QTableWidgetItem(str(value) if value else "N/A"))
    
    def add_log(self, message: str):
        """Добавление записи в лог."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # Автопрокрутка вниз
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def set_db_info(self, stats: Dict[str, Any]):
        """Установка информации о БД."""
        if not stats:
            self.info_label.setText("Нет данных")
            return
        
        text = f"""
        <h3>Статистика базы данных</h3>
        <p><b>Всего файлов:</b> {stats.get('total_files', 0)}</p>
        <p><b>Групп дубликатов:</b> {stats.get('duplicate_groups', 0)}</p>
        <p><b>Файлов в дубликатах:</b> {stats.get('duplicate_files', 0)}</p>
        <p><b>Размер БД:</b> {stats.get('db_size_mb', 0):.2f} MB</p>
        """
        self.info_label.setText(text)


class ComparisonView(QScrollArea):
    """Режим сравнения дубликатов (Зона В - Режим 2)."""
    
    file_selected = Signal(dict)  # file_info
    
    def __init__(self):
        super().__init__()
        self.image_loader = ImageLoader()
        self.current_group = None
        self.groups = []
        self.current_index = 0
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setMinimumHeight(300)
        
        # Контейнер для контента
        self.content_widget = QWidget()
        self.setWidget(self.content_widget)
        
        layout = QVBoxLayout(self.content_widget)
        
        # Навигация между группами
        nav_layout = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Предыдущая группа")
        self.next_btn = QPushButton("Следующая группа ▶")
        self.group_label = QLabel("Группа 1 из 1")
        
        nav_layout.addStretch()
        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.group_label)
        nav_layout.addWidget(self.next_btn)
        nav_layout.addStretch()
        
        layout.addLayout(nav_layout)
        
        # Сетка изображений
        self.images_layout = QGridLayout()
        layout.addLayout(self.images_layout)
        
        layout.addStretch()
    
    def _connect_signals(self):
        self.prev_btn.clicked.connect(self._prev_group)
        self.next_btn.clicked.connect(self._next_group)
        self.image_loader.image_loaded.connect(self._on_image_loaded)
        self.image_loader.image_failed.connect(self._on_image_failed)
    
    def set_groups(self, groups: List[Dict[str, Any]]):
        """Установка групп дубликатов."""
        self.groups = groups
        self.current_index = 0
        if groups:
            self._show_group(0)
        else:
            self._clear_view()
    
    def _clear_view(self):
        """Очистка представления."""
        self.current_group = None
        self.group_label.setText("Нет групп")
        
        # Очищаем сетку
        while self.images_layout.count():
            item = self.images_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    
    def _show_group(self, index: int):
        """Показ группы по индексу."""
        if not self.groups or index < 0 or index >= len(self.groups):
            return
        
        self.current_index = index
        group = self.groups[index]
        self.current_group = group
        
        self.group_label.setText(f"Группа {index + 1} из {len(self.groups)} ({group['match_type']})")
        
        # Очищаем сетку
        while self.images_layout.count():
            item = self.images_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Добавляем изображения
        file_paths = group.get('file_paths', [])
        cols = min(3, len(file_paths))
        
        for i, file_path in enumerate(file_paths):
            row = i // cols
            col = i % cols
            
            # Создаем контейнер для изображения
            frame = QFrame()
            frame.setFrameStyle(QFrame.Box)
            frame_layout = QVBoxLayout(frame)
            frame_layout.setAlignment(Qt.AlignCenter)
            
            # Label для изображения
            img_label = QLabel()
            img_label.setMinimumSize(150, 150)
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setText("Загрузка...")
            img_label.setObjectName(f"img_{i}")
            
            # Label для информации
            info_label = QLabel()
            info_label.setWordWrap(True)
            info_label.setFontPointSize(8)
            
            # Получаем информацию о файле из БД
            file_info = self._get_file_info(file_path)
            if file_info:
                info_text = f"{os.path.basename(file_path)}\n"
                info_text += f"{file_info.get('file_size', 0) / 1024:.1f} KB\n"
                sha = file_info.get('sha256', '')
                if sha:
                    info_text += f"SHA: {sha[:8]}..."
                info_label.setText(info_text)
            
            frame_layout.addWidget(img_label)
            frame_layout.addWidget(info_label)
            
            self.images_layout.addWidget(frame, row, col)
            
            # Загружаем изображение
            self.image_loader.load(file_path, (200, 200))
        
        # Обновляем кнопки
        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setEnabled(index < len(self.groups) - 1)
    
    def _get_file_info(self, file_path: str) -> Optional[Dict]:
        """Получение информации о файле из группы."""
        if not self.current_group:
            return None
        
        # Ищем файл в группе
        files = self.current_group.get('files', [])
        for f in files:
            if f.get('file_path') == file_path:
                return f
        return None
    
    def _on_image_loaded(self, path: str, pixmap: QPixmap):
        """Обработка загрузки изображения."""
        # Находим label для этого пути
        for i in range(self.images_layout.count()):
            item = self.images_layout.itemAt(i)
            if item and item.widget():
                frame = item.widget()
                if isinstance(frame, QFrame):
                    img_label = frame.findChild(QLabel)
                    if img_label and img_label.objectName().startswith("img_"):
                        # Проверяем, тот ли это путь
                        # (в реальном приложении нужно хранить mapping)
                        scaled = pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        img_label.setPixmap(scaled)
                        img_label.setText("")
                        break
    
    def _on_image_failed(self, path: str, error: str):
        """Обработка ошибки загрузки."""
        # Можно показать иконку ошибки
        pass
    
    def _prev_group(self):
        """Переход к предыдущей группе."""
        if self.current_index > 0:
            self._show_group(self.current_index - 1)
    
    def _next_group(self):
        """Переход к следующей группе."""
        if self.current_index < len(self.groups) - 1:
            self._show_group(self.current_index + 1)


class DuplicateListWidget(QTableWidget):
    """Список дубликатов в виде таблицы (Зона В - Режим 1)."""
    
    file_selected = Signal(dict)
    
    def __init__(self):
        super().__init__()
        self.image_loader = ImageLoader()
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels(["Превью", "Имя файла", "Путь", "Размер", "Дата съемки", "Статус"])
        
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
    
    def _connect_signals(self):
        self.cellDoubleClicked.connect(self._on_double_click)
        self.image_loader.image_loaded.connect(self._on_image_loaded)
    
    def set_files(self, files: List[Dict[str, Any]]):
        """Установка списка файлов."""
        self.setRowCount(0)
        
        for file_info in files:
            row = self.rowCount()
            self.insertRow(row)
            
            # Превью
            img_label = QLabel()
            img_label.setMinimumSize(50, 50)
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setText("...")
            self.setCellWidget(row, 0, img_label)
            
            # Имя файла
            name_item = QTableWidgetItem(os.path.basename(file_info.get('file_path', '')))
            self.setItem(row, 1, name_item)
            
            # Путь
            path_item = QTableWidgetItem(file_info.get('file_path', ''))
            self.setItem(row, 2, path_item)
            
            # Размер
            size = file_info.get('file_size', 0)
            size_item = QTableWidgetItem(f"{size / 1024:.1f} KB")
            self.setItem(row, 3, size_item)
            
            # Дата съемки
            dt_item = QTableWidgetItem(file_info.get('exif_dt_original', 'N/A'))
            self.setItem(row, 4, dt_item)
            
            # Статус
            status_item = QTableWidgetItem(file_info.get('status', ''))
            self.setItem(row, 5, status_item)
            
            # Сохраняем путь в первом элементе для загрузки
            img_label.setProperty("file_path", file_info.get('file_path'))
            
            # Загружаем превью
            self.image_loader.load(file_info.get('file_path'), (50, 50))
    
    def _on_image_loaded(self, path: str, pixmap: QPixmap):
        """Обработка загрузки превью."""
        for row in range(self.rowCount()):
            widget = self.cellWidget(row, 0)
            if widget and widget.property("file_path") == path:
                scaled = pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                widget.setPixmap(scaled)
                widget.setText("")
                break
    
    def _on_double_click(self, row: int, column: int):
        """Обработка двойного клика."""
        file_info = self._get_file_info(row)
        if file_info:
            self.file_selected.emit(file_info)
    
    def _get_file_info(self, row: int) -> Optional[Dict]:
        """Получение информации о файле из строки."""
        path_item = self.item(row, 2)
        if path_item:
            return {'file_path': path_item.text()}
        return None


class MainWindow(QMainWindow):
    """Главное окно приложения."""
    
    def __init__(self, db_path: str = "duplicates.db"):
        super().__init__()
        self.db_path = db_path
        self.scan_worker: Optional[ScanWorker] = None
        self.duplicate_groups = []
        
        self._setup_ui()
        self._setup_toolbar()
        self._connect_signals()
        
        self.setWindowTitle("Photo Duplicate Finder")
        self.setMinimumSize(1200, 800)
        
        # Применяем темную тему
        self._apply_dark_theme()
    
    def _setup_ui(self):
        """Настройка основного интерфейса."""
        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Основной layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Splitter для разделения основной области и нижней панели
        main_splitter = QSplitter(Qt.Vertical)
        
        # Верхняя часть (Sidebar + Main View)
        top_splitter = QSplitter(Qt.Horizontal)
        
        # Sidebar (Зона Б)
        self.sidebar = self._create_sidebar()
        top_splitter.addWidget(self.sidebar)
        
        # Main View (Зона В)
        self.main_view_container = QWidget()
        main_view_layout = QVBoxLayout(self.main_view_container)
        
        # Переключатель режимов
        view_mode_layout = QHBoxLayout()
        self.list_mode_btn = QPushButton("📋 Список")
        self.compare_mode_btn = QPushButton("🔍 Сравнение")
        self.list_mode_btn.setCheckable(True)
        self.compare_mode_btn.setCheckable(True)
        self.list_mode_btn.setChecked(True)
        
        view_mode_layout.addWidget(self.list_mode_btn)
        view_mode_layout.addWidget(self.compare_mode_btn)
        view_mode_layout.addStretch()
        
        main_view_layout.addLayout(view_mode_layout)
        
        # Контейнер для переключения видов
        self.view_stack = QStackedWidget()
        
        # Список
        self.list_view = DuplicateListWidget()
        self.view_stack.addWidget(self.list_view)
        
        # Сравнение
        self.compare_view = ComparisonView()
        self.view_stack.addWidget(self.compare_view)
        
        main_view_layout.addWidget(self.view_stack)
        
        top_splitter.addWidget(self.main_view_container)
        
        # Устанавливаем размеры splitter
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 3)
        
        main_splitter.addWidget(top_splitter)
        
        # Нижняя панель (Зона Г)
        self.properties_panel = PropertiesPanel()
        self.properties_panel.setMaximumHeight(250)
        main_splitter.addWidget(self.properties_panel)
        
        main_splitter.setStretchFactor(0, 3)
        main_splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(main_splitter)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Готов к сканированию")
        self.status_bar.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)
    
    def _create_sidebar(self) -> QWidget:
        """Создание боковой панели."""
        sidebar = QWidget()
        layout = QVBoxLayout(sidebar)
        
        # Дерево папок
        tree_label = QLabel("<b>Папки</b>")
        layout.addWidget(tree_label)
        
        self.folder_tree = QTreeView()
        self.folder_tree.setHeaderHidden(True)
        layout.addWidget(self.folder_tree)
        
        # Фильтры
        filter_label = QLabel("<b>Фильтры</b>")
        layout.addWidget(filter_label)
        
        self.filter_list = QListWidget()
        self.filter_list.addItem("Все файлы")
        self.filter_list.addItem("Только дубликаты")
        self.filter_list.setMaximumHeight(100)
        layout.addWidget(self.filter_list)
        
        layout.addStretch()
        
        return sidebar
    
    def _setup_toolbar(self):
        """Настройка панели инструментов (Зона А)."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Кнопка выбора папки
        self.select_folder_btn = QPushButton("📁 Выбрать папку")
        toolbar.addWidget(self.select_folder_btn)
        toolbar.addSeparator()
        
        # Кнопка старт
        self.start_btn = QPushButton("▶ Старт")
        self.start_btn.setStyleSheet("font-weight: bold; background-color: #4CAF50; color: white; padding: 5px 15px;")
        toolbar.addWidget(self.start_btn)
        toolbar.addSeparator()
        
        # Кнопка стоп
        self.stop_btn = QPushButton("⏹ Стоп")
        self.stop_btn.setEnabled(False)
        toolbar.addWidget(self.stop_btn)
        toolbar.addSeparator()
        
        # Кнопка очистки БД
        self.clear_db_btn = QPushButton("🗑 Очистить БД")
        toolbar.addWidget(self.clear_db_btn)
        toolbar.addSeparator()
        
        # Кнопка экспорта
        self.export_btn = QPushButton("📊 Экспорт")
        toolbar.addWidget(self.export_btn)
        toolbar.addSeparator()
        
        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
    
    def _connect_signals(self):
        """Подключение сигналов."""
        self.select_folder_btn.clicked.connect(self._select_folder)
        self.start_btn.clicked.connect(self._start_scan)
        self.stop_btn.clicked.connect(self._stop_scan)
        self.clear_db_btn.clicked.connect(self._clear_database)
        self.export_btn.clicked.connect(self._export_results)
        
        self.list_mode_btn.toggled.connect(self._on_view_mode_changed)
        self.compare_mode_btn.toggled.connect(self._on_view_mode_changed)
        
        self.list_view.file_selected.connect(self._on_file_selected)
    
    def _apply_dark_theme(self):
        """Применение темной темы."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QToolBar {
                background-color: #3c3f41;
                border-bottom: 1px solid #555555;
                padding: 5px;
            }
            QPushButton {
                background-color: #4c5052;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #5c6062;
            }
            QPushButton:pressed {
                background-color: #3c4042;
            }
            QPushButton:disabled {
                background-color: #3c3f41;
                color: #888888;
            }
            QTableWidget {
                background-color: #3c3f41;
                color: white;
                gridline-color: #555555;
            }
            QTableWidget::item:selected {
                background-color: #0d99ff;
            }
            QHeaderView::section {
                background-color: #4c5052;
                color: white;
                border: none;
                padding: 5px;
            }
            QTreeWidget, QTreeView {
                background-color: #3c3f41;
                color: white;
            }
            QTreeWidget::item:selected, QTreeView::item:selected {
                background-color: #0d99ff;
            }
            QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #3c3f41;
            }
            QTabBar::tab {
                background-color: #4c5052;
                color: white;
                padding: 5px 10px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #3c3f41;
            }
            QTextEdit {
                background-color: #2b2b2b;
                color: #cccccc;
                border: none;
            }
            QProgressBar {
                border: 1px solid #555555;
                border-radius: 3px;
                background-color: #3c3f41;
                color: white;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #0d99ff;
            }
            QStatusBar {
                background-color: #3c3f41;
                color: white;
            }
            QScrollArea {
                border: none;
            }
            QFrame {
                background-color: #3c3f41;
            }
        """)
    
    @Slot()
    def _select_folder(self):
        """Выбор папки для сканирования."""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сканирования",
            "",
            QFileDialog.ShowDirsOnly
        )
        
        if folder:
            self.selected_folder = folder
            self.status_label.setText(f"Папка: {folder}")
            self.properties_panel.add_log(f"Выбрана папка: {folder}")
    
    @Slot()
    def _start_scan(self):
        """Запуск сканирования."""
        if not hasattr(self, 'selected_folder'):
            QMessageBox.warning(
                self,
                "Ошибка",
                "Сначала выберите папку для сканирования!"
            )
            return
        
        # Блокируем кнопку старта
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.select_folder_btn.setEnabled(False)
        
        # Показываем прогресс бар
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Сканирование...")
        
        self.properties_panel.add_log("Запуск сканирования...")
        
        # Создаем и запускаем воркер
        self.scan_worker = ScanWorker(self.selected_folder, self.db_path)
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.status.connect(self._on_scan_status)
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.error.connect(self._on_scan_error)
        
        self.scan_worker.start()
    
    @Slot()
    def _stop_scan(self):
        """Остановка сканирования."""
        if self.scan_worker:
            self.properties_panel.add_log("Остановка сканирования...")
            self.scan_worker.stop()
    
    @Slot(int, int, str)
    def _on_scan_progress(self, current: int, total: int, stage: str):
        """Обновление прогресса сканирования."""
        if total > 0:
            percent = int((current / total) * 100)
            self.progress_bar.setValue(percent)
            self.progress_bar.setFormat(f"{stage}: {current}/{total} ({percent}%)")
        else:
            self.progress_bar.setFormat(f"{stage}: {current}")
    
    @Slot(str)
    def _on_scan_status(self, message: str):
        """Обновление статуса сканирования."""
        self.status_label.setText(message)
        self.properties_panel.add_log(message)
    
    @Slot(dict)
    def _on_scan_finished(self, result: dict):
        """Завершение сканирования."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.select_folder_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        self.properties_panel.add_log(f"Сканирование завершено за {result.get('duration_seconds', 0):.1f} сек")
        
        # Сохраняем группы дубликатов
        self.duplicate_groups = result.get('groups', [])
        
        # Обновляем представление
        if self.duplicate_groups:
            self.compare_view.set_groups(self.duplicate_groups)
            
            # Переключаемся на режим сравнения
            self.compare_mode_btn.setChecked(True)
            
            # Показываем все файлы из дубликатов в списке
            all_files = []
            for group in self.duplicate_groups:
                all_files.extend(group.get('files', []))
            self.list_view.set_files(all_files)
        
        # Обновляем инфо о БД
        stats = result.get('stats', {})
        self.properties_panel.set_db_info(stats)
        
        # Показываем уведомление
        QMessageBox.information(
            self,
            "Сканирование завершено",
            f"Найдено {len(self.duplicate_groups)} групп дубликатов"
        )
    
    @Slot(str)
    def _on_scan_error(self, error: str):
        """Ошибка сканирования."""
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.select_folder_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        self.properties_panel.add_log(f"Ошибка: {error}")
        
        QMessageBox.critical(
            self,
            "Ошибка сканирования",
            f"Произошла ошибка: {error}"
        )
    
    @Slot()
    def _clear_database(self):
        """Очистка базы данных."""
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Вы уверены? Все данные будут удалены!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            from app.core import DuplicateFinder
            finder = DuplicateFinder(self.db_path)
            finder.clear_database()
            finder.close()
            
            self.properties_panel.add_log("База данных очищена")
            self.duplicate_groups = []
            self.list_view.setRowCount(0)
            self.compare_view._clear_view()
            self.properties_panel.set_db_info({})
            self.status_label.setText("База данных очищена")
    
    @Slot()
    def _export_results(self):
        """Экспорт результатов."""
        if not self.duplicate_groups:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Нет результатов для экспорта!"
            )
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт результатов",
            "duplicates.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("Group ID,Match Type,File Path,Size,SHA256\n")
                    
                    for group in self.duplicate_groups:
                        group_id = group.get('group_id', 0)
                        match_type = group.get('match_type', '')
                        
                        for file_info in group.get('files', []):
                            path = file_info.get('file_path', '')
                            size = file_info.get('file_size', 0)
                            sha = file_info.get('sha256', '')
                            
                            f.write(f"{group_id},{match_type},{path},{size},{sha}\n")
                
                self.properties_panel.add_log(f"Результаты экспортированы в {file_path}")
                QMessageBox.information(
                    self,
                    "Экспорт завершен",
                    f"Результаты сохранены в {file_path}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Ошибка экспорта",
                    f"Не удалось экспортировать: {str(e)}"
                )
    
    @Slot(bool)
    def _on_view_mode_changed(self, checked: bool):
        """Переключение режима просмотра."""
        if not checked:
            return
        
        if self.sender() == self.list_mode_btn:
            self.compare_mode_btn.setChecked(False)
            self.view_stack.setCurrentIndex(0)
        elif self.sender() == self.compare_mode_btn:
            self.list_mode_btn.setChecked(False)
            self.view_stack.setCurrentIndex(1)
    
    @Slot(dict)
    def _on_file_selected(self, file_info: dict):
        """Выбор файла в списке."""
        # Показываем EXIF данные
        self.properties_panel.set_exif_data(file_info)
        
        # Переходим на вкладку EXIF
        self.properties_panel.setCurrentIndex(0)

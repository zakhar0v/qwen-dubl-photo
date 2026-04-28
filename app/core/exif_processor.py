"""
Модуль обработки EXIF данных для приложения поиска дубликатов.
Извлекает метаданные из изображений и формирует сигнатуры.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import hashlib


try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class EXIFProcessor:
    """Обработчик EXIF данных изображений."""
    
    # Ключевые поля для формирования сигнатуры
    SIGNATURE_FIELDS = [
        'DateTimeOriginal',
        'Make',
        'Model',
        'GPSLatitude',
        'GPSLongitude',
        'ImageWidth',
        'ImageHeight',
        'Orientation',
        'Software',
        'Artist',
        'Copyright'
    ]
    
    def __init__(self):
        if not PIL_AVAILABLE:
            raise ImportError("Pillow library is required for EXIF processing. Install with: pip install Pillow")
    
    def extract_exif(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Извлечение EXIF данных из изображения.
        
        Args:
            file_path: Путь к файлу изображения
        
        Returns:
            Словарь с EXIF данными или None если данные не найдены
        """
        try:
            with Image.open(file_path) as img:
                exif_data = img._getexif()
                
                if not exif_data:
                    return None
                
                # Преобразуем числовые теги в читаемые имена
                result = {}
                for tag_id, value in exif_data.items():
                    tag_name = TAGS.get(tag_id, tag_id)
                    
                    # Обработка GPS данных
                    if tag_name == 'GPSInfo':
                        gps_data = self._process_gps(value)
                        result.update(gps_data)
                    else:
                        result[tag_name] = self._normalize_value(value)
                
                return result
        except Exception as e:
            # Если не удалось прочитать EXIF, возвращаем None
            return None
    
    def _normalize_value(self, value: Any) -> Any:
        """Нормализация значения EXIF тега."""
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8', errors='ignore').strip()
            except:
                return str(value)
        elif isinstance(value, tuple):
            # Обработка рациональных чисел и других кортежей
            if len(value) == 2 and isinstance(value[0], int) and isinstance(value[1], int):
                # Рациональное число
                if value[1] != 0:
                    return value[0] / value[1]
                else:
                    return float(value[0])
            return str(value)
        elif isinstance(value, (int, float, str)):
            return value
        else:
            return str(value)
    
    def _process_gps(self, gps_info: Dict) -> Dict[str, Any]:
        """Обработка GPS данных."""
        result = {}
        
        lat = None
        lon = None
        
        for tag_id, value in gps_info.items():
            tag_name = GPSTAGS.get(tag_id, tag_id)
            
            if tag_name == 'GPSLatitude':
                lat = self._convert_gps_coordinates(value)
            elif tag_name == 'GPSLongitude':
                lon = self._convert_gps_coordinates(value)
            elif tag_name == 'GPSLatitudeRef':
                if lat is not None and value == 'S':
                    lat = -lat
            elif tag_name == 'GPSLongitudeRef':
                if lon is not None and value == 'W':
                    lon = -lon
        
        if lat is not None:
            result['GPSLatitude'] = round(lat, 6)
        if lon is not None:
            result['GPSLongitude'] = round(lon, 6)
        
        return result
    
    def _convert_gps_coordinates(self, value: Tuple) -> float:
        """Преобразование GPS координат из формата EXIF в десятичные градусы."""
        if len(value) < 3:
            return 0.0
        
        degrees = self._rational_to_float(value[0])
        minutes = self._rational_to_float(value[1])
        seconds = self._rational_to_float(value[2])
        
        return degrees + (minutes / 60.0) + (seconds / 3600.0)
    
    def _rational_to_float(self, rational: Tuple) -> float:
        """Преобразование рационального числа в float."""
        if isinstance(rational, (int, float)):
            return float(rational)
        if len(rational) >= 2 and rational[1] != 0:
            return rational[0] / rational[1]
        return 0.0
    
    def create_signature(self, exif_data: Dict[str, Any]) -> Optional[str]:
        """
        Создание сигнатуры из EXIF данных.
        
        Args:
            exif_data: Словарь с EXIF данными
        
        Returns:
            Строка-сигнатура или None если нет данных
        """
        if not exif_data:
            return None
        
        sig_parts = []
        
        for key in self.SIGNATURE_FIELDS:
            value = exif_data.get(key)
            if value is not None:
                # Форматируем значение для сигнатуры
                if isinstance(value, float):
                    formatted_value = f"{value:.6f}"
                elif isinstance(value, tuple):
                    formatted_value = str(value)
                else:
                    formatted_value = str(value).strip()
                
                sig_parts.append(f"{key}={formatted_value}")
        
        if not sig_parts:
            return None
        
        # Сортируем части для консистентности и объединяем
        signature = "|".join(sorted(sig_parts))
        
        # Хешируем для компактности (опционально)
        # return hashlib.sha256(signature.encode()).hexdigest()[:32]
        return signature
    
    def extract_datetime_original(self, exif_data: Dict[str, Any]) -> Optional[str]:
        """
        Извлечение даты съемки в стандартном формате.
        
        Args:
            exif_data: Словарь с EXIF данными
        
        Returns:
            Дата в формате YYYY-MM-DD HH:MM:SS или None
        """
        dt_original = exif_data.get('DateTimeOriginal')
        
        if not dt_original:
            return None
        
        try:
            # EXIF дата обычно в формате "YYYY:MM:DD HH:MM:SS"
            if isinstance(dt_original, str):
                # Заменяем разделители дат
                dt_original = dt_original.replace(':', '-', 2)
                dt_obj = datetime.strptime(dt_original, '%Y-%m-%d %H:%M:%S')
                return dt_obj.strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            pass
        
        return None
    
    def process_file(self, file_path: str) -> Dict[str, Any]:
        """
        Полная обработка файла и извлечение всех необходимых данных.
        
        Args:
            file_path: Путь к файлу
        
        Returns:
            Словарь с обработанными данными для БД
        """
        result = {
            'exif_signature': None,
            'exif_dt_original': None,
            'exif_make': None,
            'exif_model': None
        }
        
        exif_data = self.extract_exif(file_path)
        
        if exif_data:
            result['exif_signature'] = self.create_signature(exif_data)
            result['exif_dt_original'] = self.extract_datetime_original(exif_data)
            result['exif_make'] = exif_data.get('Make')
            result['exif_model'] = exif_data.get('Model')
        
        return result

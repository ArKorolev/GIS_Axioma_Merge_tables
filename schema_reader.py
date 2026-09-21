"""
Модуль чтения схем источников — быстрые парсеры без openfile.

Все методы — статические, не требуют экземпляра.
Зависимости: constants (GEOJSON_SCHEMA_BUFFER), os, json, sqlite3.
Никаких Qt, никаких axipy.
"""

import os
import json
import sqlite3

from .constants import GEOJSON_SCHEMA_BUFFER


class SchemaReader:
    """Быстрые парсеры схем для всех поддерживаемых форматов."""

    @staticmethod
    def detect_mif_encoding(mif_path):
        """Определение кодировки MIF-файла по первым 4 КБ."""
        try:
            with open(mif_path, 'rb') as f:
                raw = f.read(4096)
            if raw.startswith(b'\xef\xbb\xbf'):
                raw = raw[3:]
            text = raw.decode('ascii', errors='ignore')
            if 'WindowsCyrillic' in text:
                return 'windows-1251'
            if 'UTF8' in text or 'UTF-8' in text:
                return 'utf-8'
            if 'WindowsLatin1' in text:
                return 'cp1252'
        except Exception:
            pass
        return 'windows-1251'

    @staticmethod
    def parse_mif_header(mif_path):
        """Парсинг MIF-файла: чтение секции Columns."""
        encoding = SchemaReader.detect_mif_encoding(mif_path)
        columns = []
        in_columns = False
        try:
            with open(mif_path, 'r', encoding=encoding, errors='replace') as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.lower().startswith('columns'):
                        in_columns = True
                        continue
                    if stripped.lower() == 'data':
                        break
                    if in_columns and stripped:
                        parts = stripped.split(None, 1)
                        if len(parts) == 2:
                            columns.append((parts[0], parts[1]))
                        elif len(parts) == 1:
                            columns.append((parts[0], ''))
        except Exception:
            pass
        return columns

    @staticmethod
    def parse_tab_header(tab_path):
        """Чтение .tab-файла как текста: извлечение секции Fields."""
        columns = []
        try:
            with open(tab_path, 'r', encoding='windows-1251', errors='replace') as f:
                in_fields = False
                for line in f:
                    stripped = line.strip()
                    low = stripped.lower()

                    if low.startswith('fields '):
                        in_fields = True
                        continue

                    if not in_fields:
                        continue

                    if not stripped:
                        if columns:
                            break
                        continue

                    if low.startswith('begin_') or low.startswith('end_'):
                        break

                    field_line = stripped.rstrip(';').strip()
                    if field_line:
                        parts = field_line.split(None, 1)
                        if len(parts) >= 2:
                            col_name = parts[0].strip('"').strip("'")
                            col_type = parts[1]
                        elif len(parts) == 1:
                            col_name = parts[0].strip('"').strip("'")
                            col_type = ''
                        columns.append((col_name, col_type))
        except Exception:
            pass
        return columns

    @staticmethod
    def parse_dbf_header(shp_path):
        """Чтение DBF по байтам: извлечение описаний полей."""
        dbf_path = shp_path.rsplit('.', 1)[0] + '.dbf'
        if not os.path.exists(dbf_path):
            return []
        columns = []
        try:
            with open(dbf_path, 'rb') as f:
                header = f.read(32)
                if len(header) < 32:
                    return []
                while True:
                    field_desc = f.read(32)
                    if len(field_desc) < 32 or field_desc[0] == 0x0D:
                        break
                    name = field_desc[:11].split(b'\x00')[0].decode('windows-1251', errors='replace')
                    type_char = chr(field_desc[11])
                    type_map = {
                        'C': 'Char', 'N': 'Float', 'F': 'Float',
                        'D': 'Date', 'L': 'Logical', 'I': 'Integer'
                    }
                    col_type = type_map.get(type_char, type_char)
                    columns.append((name, col_type))
        except Exception:
            pass
        return columns

    @staticmethod
    def parse_csv_header(csv_path):
        """Парсинг CSV: чтение первой строки как заголовка."""
        columns = []
        try:
            with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
                first_line = f.readline()
            if first_line:
                names = first_line.strip().split(',')
                columns = [(name.strip().strip('"').strip("'"), '') for name in names if name.strip()]
        except Exception:
            pass
        return columns

    @staticmethod
    def parse_geojson_header(geojson_path):
        """Чтение GeoJSON с fallback: 256 КБ → 1 МБ → весь файл.

        Извлекает свойства первого объекта для определения схемы.
        """
        try:
            with open(geojson_path, 'rb') as f:
                raw = f.read(GEOJSON_SCHEMA_BUFFER)
            text = raw.decode('utf-8', errors='replace')

            idx = text.find('"properties"')
            if idx < 0:
                # Возможно, "properties" за пределами буфера — читаем больше
                with open(geojson_path, 'rb') as f:
                    raw = f.read(GEOJSON_SCHEMA_BUFFER * 4)
                text = raw.decode('utf-8', errors='replace')
                idx = text.find('"properties"')
                if idx < 0:
                    return []

            brace_start = text.find('{', idx)
            if brace_start < 0:
                return []

            depth = 0
            in_string = False
            i = brace_start
            while i < len(text):
                c = text[i]
                if in_string:
                    if c == '\\':
                        i += 1
                    elif c == '"':
                        in_string = False
                else:
                    if c == '"':
                        in_string = True
                    elif c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            break
                i += 1

            if depth != 0:
                # JSON не закрыт в пределах буфера — читаем весь файл
                with open(geojson_path, 'rb') as f:
                    text = f.read().decode('utf-8', errors='replace')
                brace_start = text.find('{', text.find('"properties"'))
                if brace_start < 0:
                    return []
                depth = 0
                in_string = False
                i = brace_start
                while i < len(text):
                    c = text[i]
                    if in_string:
                        if c == '\\':
                            i += 1
                        elif c == '"':
                            in_string = False
                    else:
                        if c == '"':
                            in_string = True
                        elif c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                break
                    i += 1
                if depth != 0:
                    return []

            props = json.loads(text[brace_start:i + 1])
            if not isinstance(props, dict):
                return []

            columns = []
            for key, val in props.items():
                if isinstance(val, bool):
                    col_type = 'Logical'
                elif isinstance(val, int):
                    col_type = 'Integer'
                elif isinstance(val, float):
                    col_type = 'Float'
                else:
                    col_type = 'Char'
                columns.append((key, col_type))
            return columns
        except Exception:
            pass
        return []

    @staticmethod
    def parse_gpkg_header(gpkg_path):
        """Чтение GeoPackage через SQLite: извлечение схемы первой таблицы."""
        conn = None
        try:
            conn = sqlite3.connect(gpkg_path)

            cursor = conn.execute(
                "SELECT table_name FROM gpkg_geometry_columns LIMIT 1"
            )
            row = cursor.fetchone()

            if row:
                table_name = row[0]
            else:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'gpkg_%' AND name NOT LIKE 'rtree_%' "
                    "AND name NOT LIKE 'sqlite_%' LIMIT 1"
                )
                row = cursor.fetchone()
                if not row:
                    return []
                table_name = row[0]

            cursor = conn.execute(f'PRAGMA table_info("{table_name}")')
            columns = []
            for col_row in cursor.fetchall():
                col_name = col_row[1]
                col_type_raw = (col_row[2] or '').lower()

                if 'int' in col_type_raw:
                    col_type = 'Integer'
                elif 'real' in col_type_raw or 'float' in col_type_raw or 'double' in col_type_raw:
                    col_type = 'Float'
                elif 'text' in col_type_raw or 'char' in col_type_raw:
                    col_type = 'Char'
                elif 'bool' in col_type_raw:
                    col_type = 'Logical'
                elif 'date' in col_type_raw:
                    col_type = 'Date'
                else:
                    col_type = 'Char'
                columns.append((col_name, col_type))

            return columns
        except Exception:
            pass
        return []

    @staticmethod
    def _normalize_type(type_str):
        """Нормализует строку типа: 'Char(50)' → 'char', 'Integer' → 'integer'."""
        return type_str.lower().split('(')[0].strip()

    @staticmethod
    def schemas_match(reference, candidate):
        """Проверка совместимости схем с нормализацией типов."""
        if len(reference) != len(candidate):
            return False
        for (ref_name, ref_type), (cand_name, cand_type) in zip(reference, candidate):
            if ref_name != cand_name:
                return False
            if SchemaReader._normalize_type(ref_type) != SchemaReader._normalize_type(cand_type):
                return False
        return True

    @staticmethod
    def detect_csv_delimiter(filepath):
        """Автоопределение разделителя CSV по первой строке."""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                first_line = f.readline()
            comma_count = first_line.count(',')
            semicolon_count = first_line.count(';')
            tab_count = first_line.count('\t')
            if tab_count > comma_count and tab_count > semicolon_count:
                return '\t'
            if semicolon_count > comma_count:
                return ';'
            return ','
        except Exception:
            return ','

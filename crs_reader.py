"""
Модуль чтения систем координат — быстрые парсеры СК.

Все методы — статические, не требуют экземпляра.
Зависимости: constants (WGS84_FORMATS), axipy (CoordSystem, provider_manager),
             sqlite3, os.
Импортирует detect_mif_encoding из schema_reader (DAG: crs_reader → schema_reader).
Не импортирует PySide2. Не импортирует merge_engine на уровне модуля
  (ленивый импорт внутри from_file_fast для MIF).
"""

import os
import sqlite3

from axipy import CoordSystem, provider_manager

from .constants import WGS84_FORMATS
from .schema_reader import SchemaReader


class CrsReader:
    """Быстрые парсеры систем координат для всех поддерживаемых форматов."""

    @staticmethod
    def is_non_earth(crs):
        """Проверка, является ли СК план-схемой (NonEarth)."""
        if crs is None:
            return False
        for mname in ('is_non_earth', 'isNonEarth', 'non_earth'):
            method = getattr(crs, mname, None)
            if callable(method):
                try:
                    return bool(method())
                except Exception:
                    continue
        for aname in ('non_earth', 'isNonEarth', 'is_non_earth'):
            try:
                val = getattr(crs, aname, None)
                if val is not None:
                    return bool(val)
            except Exception:
                continue
        try:
            wkt = (crs.wkt or '').lower()
            if 'local_cs' in wkt or 'nonearth' in wkt or 'non-earth' in wkt or 'non earth' in wkt:
                return True
        except Exception:
            pass
        try:
            title = (crs.title or '').lower()
            if 'nonearth' in title or 'план-схема' in title or 'non-earth' in title or 'non earth' in title:
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def parse_from_tab(tab_path):
        """Парсинг СК из .tab-файла: поиск строки CoordSys."""
        try:
            with open(tab_path, 'r', encoding='windows-1251', errors='replace') as f:
                content = f.read()
            low = content.lower()
            cs_idx = low.find('coordsys')
            if cs_idx >= 0:
                line_end = content.find('\n', cs_idx)
                if line_end < 0:
                    line_end = len(content)
                cs_line = content[cs_idx:line_end].strip()
                is_ne = 'nonearth' in cs_line.lower()
                return cs_line, is_ne
            return "NonEarth (план-схема, нет CoordSys)", True
        except Exception:
            pass
        return None, False

    @staticmethod
    def parse_from_mif(mif_path):
        """Парсинг СК из MIF-файла: поиск строки CoordSys."""
        encoding = SchemaReader.detect_mif_encoding(mif_path)
        try:
            with open(mif_path, 'r', encoding=encoding, errors='replace') as f:
                for line in f:
                    stripped = line.strip()
                    low = stripped.lower()
                    if low.startswith('coordsys'):
                        is_ne = 'nonearth' in low
                        return stripped, is_ne
                    if low == 'data':
                        break
        except Exception:
            pass
        return "NonEarth (план-схема, нет CoordSys)", True

    @staticmethod
    def parse_from_prj(shp_path):
        """Чтение WKT из .prj-файла для SHP."""
        prj_path = os.path.splitext(shp_path)[0] + '.prj'
        if not os.path.exists(prj_path):
            return None, False
        try:
            with open(prj_path, 'r', encoding='utf-8', errors='replace') as f:
                wkt = f.read().strip()
            if wkt:
                is_ne = 'LOCAL_CS' in wkt
                return wkt[:200], is_ne
        except Exception:
            pass
        return None, False

    @staticmethod
    def parse_from_geojson(geojson_path):
        """Парсинг СК из GeoJSON: поиск поля 'crs'."""
        try:
            with open(geojson_path, 'rb') as f:
                raw = f.read(8192)
            text = raw.decode('utf-8', errors='replace')
            idx = text.find('"crs"')
            if idx >= 0:
                snippet = text[idx:idx + 200]
                return snippet, False
            return 'WGS84 (default)', False
        except Exception:
            pass
        return None, False

    @staticmethod
    def parse_from_gpkg(gpkg_path):
        """Чтение СК из GeoPackage через SQLite."""
        conn = None
        try:
            conn = sqlite3.connect(gpkg_path)
            cursor = conn.execute(
                "SELECT srs_name, definition FROM gpkg_spatial_ref_sys LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                srs_name, definition = row
                is_ne = 'LOCAL_CS' in (definition or '') or 'nonearth' in (srs_name or '').lower()
                return srs_name or 'Unknown', is_ne
        except Exception:
            pass
        finally:
            if conn is not None:
                conn.close()
        return None, False

    @staticmethod
    def from_file_fast(filepath, fmt_key):
        """Пытается получить CoordSystem без открытия через провайдер (где возможно).

        Для SHP, GPKG и GeoJSON — читает WKT напрямую.
        Для TAB и MIF — открывает через провайдер (CoordSys-строка не является WKT).
        Для MIF — конвертация в temp TAB через MergeEngine.mif_to_temp_tab
                  (ленивый импорт, чтобы избежать циклического импорта на уровне модуля).
        """
        if fmt_key == "shp":
            prj_path = os.path.splitext(filepath)[0] + '.prj'
            if os.path.exists(prj_path):
                try:
                    with open(prj_path, 'r', encoding='utf-8', errors='replace') as f:
                        wkt = f.read().strip()
                    if wkt and 'LOCAL_CS' not in wkt:
                        return CoordSystem.from_wkt(wkt)
                except Exception:
                    pass
            return None

        if fmt_key == "gpkg":
            conn = None
            try:
                conn = sqlite3.connect(filepath)
                cursor = conn.execute(
                    "SELECT definition FROM gpkg_spatial_ref_sys LIMIT 1"
                )
                row = cursor.fetchone()
                if row and row[0]:
                    wkt = row[0]
                    if 'LOCAL_CS' not in wkt:
                        return CoordSystem.from_wkt(wkt)
            except Exception:
                pass
            finally:
                if conn is not None:
                    conn.close()
            return None

        if fmt_key == "geojson":
            crs_str, _ = CrsReader.parse_from_geojson(filepath)
            if crs_str == 'WGS84 (default)':
                try:
                    return CoordSystem.from_epsg(4326)
                except Exception:
                    pass
            return None

        if fmt_key == "tab":
            try:
                table = provider_manager.openfile(filepath)
                crs = table.coordsystem
                table.close()
                return crs
            except Exception:
                return None

        # MIF: конвертация в temp TAB (CoordSys-строка не является WKT)
        # Ленивый импорт MergeEngine — избегает циклического импорта
        if fmt_key == "mif":
            from .merge_engine import MergeEngine
            temp_tab = MergeEngine.mif_to_temp_tab(filepath)
            try:
                table = provider_manager.openfile(temp_tab)
                crs = table.coordsystem
                table.close()
                return crs
            except Exception:
                return None
            finally:
                MergeEngine.cleanup_tab_files(temp_tab)

        return None

"""
Движок слияния — создание приёмника, генерация записей, экспорт.

MergeEngine — экземпляр, создаётся MergeDialog.
Принимает коллбэки: log_callback(msg), progress_callback(value),
                     on_pause_check() — блокирует при паузе, возвращает True при отмене,
                     on_cancel_check() — только проверяет отмену (без блокировки).
Зависимости: constants (OGR_CREATE_DATA_KEYS, OUTPUT_FORMATS, OGR_DRIVERS),
             axipy (provider_manager), os, tempfile, uuid, time.
Не импортирует PySide2. Не знает про MergeDialog.
"""

import os
import time
import tempfile
import uuid

from axipy import provider_manager

from .constants import OGR_CREATE_DATA_KEYS, OUTPUT_FORMATS, OGR_DRIVERS


class MergeEngine:
    """Движок слияния: создание приёмника, генерация записей, экспорт."""

    def __init__(self, out_format, crs, log_callback=None,
                 progress_callback=None):
        self._out_format = out_format
        self._crs = crs
        self._log = log_callback or (lambda msg: None)
        self._progress = progress_callback or (lambda val: None)
        self._ogr_create_data = None

    @staticmethod
    def get_temp_tab_path():
        temp_dir = tempfile.gettempdir()
        unique_name = f"merge_tmp_{uuid.uuid4().hex}"
        return os.path.join(temp_dir, unique_name + ".tab")

    @staticmethod
    def cleanup_tab_files(tab_path):
        base = tab_path.rsplit(".", 1)[0]
        for ext in (".tab", ".dat", ".id", ".map", ".ind"):
            path = base + ext
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    @staticmethod
    def mif_to_temp_tab(mif_path):
        temp_tab = MergeEngine.get_temp_tab_path()
        provider_manager.mif.convert_to_tab(mif_path, temp_tab)
        return temp_tab

    def ensure_utf8_bom(self, filepath):
        """Добавляет BOM к файлу, если его нет. Chunked copy по 64 КБ."""
        try:
            with open(filepath, 'rb') as f:
                first_bytes = f.read(3)
            if first_bytes == b'\xef\xbb\xbf':
                return
            tmp_path = filepath + '.tmp_bom'
            with open(filepath, 'rb') as src, open(tmp_path, 'wb') as dst:
                dst.write(b'\xef\xbb\xbf')
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
            os.replace(tmp_path, filepath)
        except Exception as e:
            self._log(f"Не удалось добавить BOM: {e}")

    def get_source_schema_for_export(self, source, use_open, source_ext):
        if use_open:
            return source.schema
        if source_ext == "mif":
            temp_tab = MergeEngine.mif_to_temp_tab(source)
            try:
                table = provider_manager.openfile(temp_tab)
                schema = table.schema
                table.close()
                return schema
            finally:
                MergeEngine.cleanup_tab_files(temp_tab)
        table = provider_manager.openfile(source)
        schema = table.schema
        table.close()
        return schema

    def create_destination(self, out_file, schema):
        provider_type = OUTPUT_FORMATS[self._out_format][2]
        if provider_type == "ogr":
            layer_name = os.path.splitext(os.path.basename(out_file))[0]
            driver = OGR_DRIVERS.get(self._out_format)
            if driver is not None:
                if self._ogr_create_data is not None:
                    try:
                        dest = provider_manager.ogr.get_destination(
                            out_file, layer_name, schema,
                            create_data=self._ogr_create_data
                        )
                        if dest is not None:
                            return dest
                    except Exception:
                        pass
                for key in OGR_CREATE_DATA_KEYS:
                    cd = {key: driver}
                    try:
                        dest = provider_manager.ogr.get_destination(
                            out_file, layer_name, schema, create_data=cd
                        )
                        if dest is not None:
                            self._ogr_create_data = cd
                            return dest
                    except TypeError:
                        continue
                    except Exception:
                        continue
                raise RuntimeError(
                    f"Не удалось создать destination для OGR-формата "
                    f"'{self._out_format}' (драйвер '{driver}'). "
                    f"Ни один из вариантов передачи драйвера не сработал."
                )
            else:
                raise RuntimeError(
                    f"Неизвестный OGR-драйвер для формата '{self._out_format}'"
                )
        elif provider_type == "csv":
            try:
                return provider_manager.csv.get_destination(
                    out_file, schema, delimiter=','
                )
            except TypeError:
                try:
                    return provider_manager.csv.get_destination(
                        out_file, schema, ','
                    )
                except TypeError:
                    return provider_manager.csv.get_destination(out_file, schema)
        else:
            dest = getattr(provider_manager, provider_type).get_destination(
                out_file, schema
            )
            if dest is None:
                raise RuntimeError(
                    f"Не удалось создать destination для формата "
                    f"'{self._out_format}'"
                )
            return dest

    def _feature_generator(self, sources, use_open, source_ext, total_count,
                           state, needs_fid_reset, needs_key_filter,
                           on_pause_check=None, on_cancel_check=None):
        """Генератор записей из источников.

        on_pause_check() — блокирует при паузе, возвращает True при отмене.
        on_cancel_check() — только проверяет отмену (без блокировки паузы).
        """
        _plus_keys = None
        fid_counter = 0

        for i, source in enumerate(sources):
            if on_pause_check is not None and on_pause_check():
                return
            state['current_file_count'] = 0
            temp_tab_path = None
            src = None
            try:
                if use_open:
                    src = source
                    src_name = src.name
                elif source_ext == "mif":
                    src_name = os.path.basename(source)
                    temp_tab_path = MergeEngine.mif_to_temp_tab(source)
                    src = provider_manager.openfile(temp_tab_path)
                else:
                    src = provider_manager.openfile(source)
                    src_name = os.path.basename(source)

                for feature in src.items():
                    if on_pause_check is not None and on_pause_check():
                        break

                    if needs_fid_reset:
                        try:
                            feature.id = fid_counter
                        except (AttributeError, TypeError):
                            pass
                        fid_counter += 1

                    if needs_key_filter:
                        if _plus_keys is None:
                            _plus_keys = tuple(
                                k for k in feature.keys()
                                if k.startswith('+')
                            )
                        if _plus_keys:
                            for key in _plus_keys:
                                try:
                                    del feature[key]
                                except (AttributeError, TypeError, KeyError):
                                    pass

                    state['current_file_count'] += 1
                    state['total_yielded'] += 1
                    yield feature

                if state['current_file_count'] == 0:
                    state['empty_sources'] += 1
                if not use_open:
                    src.close()
                    src = None
                if temp_tab_path is not None:
                    MergeEngine.cleanup_tab_files(temp_tab_path)
                    temp_tab_path = None
                if on_cancel_check is None or not on_cancel_check():
                    state['files_processed'] += 1
                    self._log(
                        f"[{i+1}/{total_count}] {src_name} - "
                        f"{state['current_file_count']:,} записей"
                    )
                    self._progress(i + 1)
            except Exception as e:
                src_name = source.name if use_open else os.path.basename(source)
                self._log(f"[{i+1}] Ошибка: {src_name} - {e}")
                state['failed_sources'].append(src_name)
            finally:
                if src is not None and not use_open:
                    try:
                        src.close()
                    except Exception:
                        pass
                    src = None
                if temp_tab_path is not None:
                    MergeEngine.cleanup_tab_files(temp_tab_path)
                    temp_tab_path = None

    def run(self, sources, use_open, source_ext, out_file,
            ref_schema_for_export=None, on_pause_check=None,
            on_cancel_check=None):
        """Главный метод слияния.

        on_pause_check — блокирует при паузе, возвращает True при отмене.
        on_cancel_check — только проверяет отмену (без блокировки).
        """
        total_count = len(sources)
        t_start = time.time()

        state = {
            'total': 0, 'current_file_count': 0, 'files_processed': 0,
            'empty_sources': 0, 'total_yielded': 0, 'failed_sources': [],
        }

        needs_fid_reset = self._out_format == "gpkg"
        needs_key_filter = OUTPUT_FORMATS[self._out_format][2] == "ogr"

        def export_callback(feature, row):
            state['total'] = row + 1
            if on_cancel_check is not None and on_cancel_check():
                return False
            return None

        try:
            if ref_schema_for_export:
                ref_ext = os.path.splitext(ref_schema_for_export)[1] \
                    .lstrip('.').lower()
                schema = self.get_source_schema_for_export(
                    ref_schema_for_export, False, ref_ext
                )
            else:
                schema = self.get_source_schema_for_export(
                    sources[0], use_open, source_ext
                )

            if self._crs is not None:
                schema.coordsystem = self._crs

            destination = self.create_destination(out_file, schema)
            destination.export(
                self._feature_generator(
                    sources, use_open, source_ext, total_count, state,
                    needs_fid_reset, needs_key_filter,
                    on_pause_check, on_cancel_check
                ),
                func_callback=export_callback
            )

            if self._out_format == "csv":
                self.ensure_utf8_bom(out_file)
        except Exception as e:
            self._log(f"\nКритическая ошибка: {e}")
            raise

        elapsed = time.time() - t_start
        cancelled = on_cancel_check() if on_cancel_check is not None else False

        return {
            'total': state['total'],
            'files_processed': state['files_processed'],
            'empty_sources': state['empty_sources'],
            'total_yielded': state['total_yielded'],
            'failed_sources': state['failed_sources'],
            'cancelled': cancelled,
            'total_count': total_count,
        }

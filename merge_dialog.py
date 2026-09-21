"""
Модуль UI и оркестрации — класс MergeDialog.
Импортирует все остальные модули.
"""

import os
import glob
import time
import traceback

from PySide2.QtWidgets import (
    QDialog, QPushButton, QLineEdit, QLabel,
    QVBoxLayout, QHBoxLayout, QFileDialog, QTextEdit, QProgressBar,
    QApplication, QCheckBox, QListWidget, QMessageBox, QComboBox
)
from PySide2.QtCore import QSettings, Qt
from axipy import (
    view_manager, provider_manager, data_manager,
    Notifications, ChooseCoordSystemDialog, CoordSystem,
    Layer, Map
)

from .constants import (
    INPUT_FORMATS, OUTPUT_FORMATS, OUTPUT_FILTERS,
    EXT_TO_OUTPUT_KEY, SCHEMA_UI_UPDATE_INTERVAL, WGS84_FORMATS
)
from .dialogs import (
    TableSelectorDialog, MidMissingDialog,
    SchemaMismatchDialog, CrsWarningDialog
)
from .schema_reader import SchemaReader
from .crs_reader import CrsReader
from .output_guard import OutputGuard
from .merge_engine import MergeEngine


class MergeDialog(QDialog):
    """Главный диалог плагина: UI, проверки, оркестрация слияния."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle("Объединение таблиц")
        self.resize(700, 550)
        self._cancelled = False
        self._paused = False
        self._is_running = False
        self.selected_tables = []
        self.all_open_tables = []
        self._crs = None
        self._out_format = "tab"
        self._crs_user_override = False
        self._settings = QSettings("AxiomaPlugins", "MergeTables")
        self._output_guard = OutputGuard(log_callback=self.log_msg, parent=self)

        self.chk_open_tables = QCheckBox("Объединить открытые таблицы")
        self.chk_open_tables.stateChanged.connect(self.toggle_source_mode)
        self.btn_select_tables = QPushButton("Выбрать таблицы...")
        self.btn_select_tables.setEnabled(False)
        self.btn_select_tables.clicked.connect(self.show_table_selector)
        open_tables_layout = QHBoxLayout()
        open_tables_layout.addWidget(self.chk_open_tables)
        open_tables_layout.addWidget(self.btn_select_tables)
        open_tables_layout.addStretch()

        self.label_src = QLabel("Исходная папка:")
        self.edit_src = QLineEdit()
        self.btn_src = QPushButton("Выбрать...")
        self.btn_src.clicked.connect(self.select_source_folder)
        self.label_format = QLabel("Формат:")
        self.combo_format = QComboBox()
        for key, (_, label) in INPUT_FORMATS.items():
            self.combo_format.addItem(label, key)
        self.combo_format.currentIndexChanged.connect(self.on_format_changed)
        src_layout = QHBoxLayout()
        src_layout.addWidget(self.label_src)
        src_layout.addWidget(self.edit_src)
        src_layout.addWidget(self.label_format)
        src_layout.addWidget(self.combo_format)
        src_layout.addWidget(self.btn_src)
        src_layout.setStretch(1, 3)
        src_layout.setSpacing(10)

        self.label_crs = QLabel("Система координат результата:")
        self.label_crs_value = QLabel("Не задана")
        self.label_crs_value.setStyleSheet("color: black; font-weight: normal;")
        self.label_crs_value.setMinimumWidth(200)
        self.btn_crs = QPushButton("Выбрать СК...")
        self.btn_crs.clicked.connect(self.select_coord_system)
        crs_layout = QHBoxLayout()
        crs_layout.addWidget(self.label_crs)
        crs_layout.addWidget(self.label_crs_value)
        crs_layout.addStretch()
        crs_layout.addWidget(self.btn_crs)
        crs_layout.setSpacing(10)

        self.label_out = QLabel("Результирующий файл:")
        self.edit_out = QLineEdit()
        self.btn_out = QPushButton("Выбрать...")
        self.btn_out.clicked.connect(self.select_output_file)
        out_layout = QHBoxLayout()
        out_layout.addWidget(self.label_out)
        out_layout.addWidget(self.edit_out)
        out_layout.addWidget(self.btn_out)
        out_layout.setStretch(1, 3)
        out_layout.setSpacing(10)
        for btn in (self.btn_src, self.btn_out, self.btn_crs):
            btn.setMinimumWidth(100)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setFormat("%p%")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        self.btn_run = QPushButton("Объединить")
        self.btn_run.clicked.connect(self.run_merge)
        self.btn_run.setMinimumHeight(40)
        self.btn_pause = QPushButton("Пауза")
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setMinimumHeight(40)
        self.btn_pause.setStyleSheet(
            "QPushButton { background: #ffdb58; color: black; }"
            "QPushButton:hover { background: #ffd700; }"
            "QPushButton:disabled { background: #ccc; color: #999; }"
        )
        self.btn_pause.setEnabled(False)
        self.btn_cancel = QPushButton("Прервать")
        self.btn_cancel.clicked.connect(self.cancel_merge)
        self.btn_cancel.setMinimumHeight(40)
        self.btn_cancel.setStyleSheet(
            "QPushButton { background: #d9534f; color: white; }"
            "QPushButton:hover { background: #c9302c; }"
            "QPushButton:disabled { background: #ccc; color: #999; }"
        )
        self.btn_cancel.setEnabled(False)
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_run)
        btn_layout.addWidget(self.btn_pause)
        btn_layout.addWidget(self.btn_cancel)

        layout = QVBoxLayout()
        layout.addLayout(open_tables_layout)
        layout.addLayout(src_layout)
        layout.addLayout(crs_layout)
        layout.addLayout(out_layout)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        self._load_settings()

    def _load_settings(self):
        input_fmt = self._settings.value("input_format", "tab", type=str)
        for i in range(self.combo_format.count()):
            if self.combo_format.itemData(i) == input_fmt:
                self.combo_format.setCurrentIndex(i)
                break
        src_dir = self._settings.value("source_dir", "", type=str)
        if src_dir:
            self.edit_src.setText(src_dir)
        out_path = self._settings.value("output_path", "", type=str)
        if out_path:
            self.edit_out.setText(out_path)
        out_fmt = self._settings.value("output_format", "tab", type=str)
        if out_fmt in OUTPUT_FORMATS:
            self._out_format = out_fmt
        use_open = self._settings.value("use_open_tables", False, type=bool)
        self.chk_open_tables.setChecked(use_open)
        if self._out_format in WGS84_FORMATS:
            self._auto_set_crs_for_format()
        elif self._crs is None:
            if self._try_restore_crs():
                self.update_crs_display()

    def _save_settings(self):
        self._settings.setValue("use_open_tables", self.chk_open_tables.isChecked())
        self._settings.setValue("source_dir", self.edit_src.text())
        self._settings.setValue("input_format", self.get_source_format_key())
        self._settings.setValue("output_path", self.edit_out.text())
        self._settings.setValue("output_format", self._out_format)
        if self._crs is not None:
            try:
                wkt = self._crs.wkt
                if wkt:
                    self._settings.setValue("crs_wkt", wkt)
            except Exception:
                pass
        else:
            self._settings.remove("crs_wkt")

    def _try_restore_crs(self):
        wkt = self._settings.value("crs_wkt", "", type=str)
        if wkt:
            try:
                self._crs = CoordSystem.from_wkt(wkt)
                return True
            except Exception:
                pass
        return False

    def done(self, result):
        self._save_settings()
        super().done(result)

    def get_source_format_key(self):
        return self.combo_format.currentData()

    def get_output_extension(self):
        return OUTPUT_FORMATS[self._out_format][0]

    def get_output_provider_type(self):
        return OUTPUT_FORMATS[self._out_format][2]

    def collect_source_files(self, src_dir):
        fmt_key = self.get_source_format_key()
        extensions = INPUT_FORMATS[fmt_key][0]
        files = []
        for ext in extensions:
            files.extend(glob.glob(os.path.join(src_dir, f"*.{ext}")))
        return sorted(set(files))

    def collect_mif_files(self, src_dir):
        all_mif = sorted(glob.glob(os.path.join(src_dir, "*.mif")))
        with_mid = []
        without_mid = []
        for mif_file in all_mif:
            mid_file = mif_file.rsplit(".", 1)[0] + ".mid"
            if os.path.exists(mid_file):
                with_mid.append(mif_file)
            else:
                without_mid.append(mif_file)
        return with_mid, without_mid

    def get_source_files_for_preview(self, src_dir):
        fmt_key = self.get_source_format_key()
        if fmt_key == "mif":
            with_mid, _ = self.collect_mif_files(src_dir)
            return with_mid
        return self.collect_source_files(src_dir)

    def get_table_schema_columns(self, table):
        columns = []
        try:
            for col in table.schema:
                name = getattr(col, 'name', str(col))
                typ = str(getattr(col, 'type', ''))
                columns.append((name, typ))
        except Exception:
            pass
        return columns

    def get_schema_columns(self, source, use_open, source_ext):
        if use_open:
            return self.get_table_schema_columns(source)
        if source_ext == "mif":
            return SchemaReader.parse_mif_header(source)
        if source_ext == "tab":
            return SchemaReader.parse_tab_header(source)
        if source_ext == "shp":
            return SchemaReader.parse_dbf_header(source)
        if source_ext == "csv":
            return SchemaReader.parse_csv_header(source)
        if source_ext == "geojson":
            schema = SchemaReader.parse_geojson_header(source)
            if schema:
                return schema
        elif source_ext == "gpkg":
            schema = SchemaReader.parse_gpkg_header(source)
            if schema:
                return schema
        table = provider_manager.openfile(source)
        try:
            return self.get_table_schema_columns(table)
        finally:
            table.close()

    def get_schema_for_file(self, filepath):
        ext = os.path.splitext(filepath)[1].lstrip('.').lower()
        return self.get_schema_columns(filepath, False, ext)

    def _parse_crs_from_source(self, filepath, source_ext):
        if source_ext == "tab":
            return CrsReader.parse_from_tab(filepath)
        if source_ext == "mif":
            return CrsReader.parse_from_mif(filepath)
        if source_ext == "shp":
            return CrsReader.parse_from_prj(filepath)
        if source_ext == "geojson":
            return CrsReader.parse_from_geojson(filepath)
        if source_ext == "gpkg":
            return CrsReader.parse_from_gpkg(filepath)
        return None, False

    def _check_crs(self, sources, use_open, source_ext):
        total = len(sources)
        self.progress.setVisible(True)
        self.progress.setMaximum(total)
        self.progress.setValue(0)
        self.progress.setFormat("Проверка СК: %p%")
        QApplication.processEvents()
        crs_list = []
        for i, source in enumerate(sources):
            if use_open:
                crs = None
                for attr_name in ('coordsystem', 'coord_system', 'crs', 'srs', 'projection'):
                    crs = getattr(source, attr_name, None)
                    if crs is not None:
                        break
                if crs is not None:
                    crs_str = getattr(crs, 'title', None) or str(crs)
                    is_ne = CrsReader.is_non_earth(crs)
                else:
                    crs_str = None
                    is_ne = False
            else:
                crs_str, is_ne = self._parse_crs_from_source(source, source_ext)
            crs_list.append((crs_str, is_ne))
            if (i + 1) % SCHEMA_UI_UPDATE_INTERVAL == 0 or i + 1 == total:
                self.progress.setValue(i + 1)
                QApplication.processEvents()
        self.progress.setFormat("%p%")
        self.progress.setValue(total)
        non_earth_count = sum(1 for _, is_ne in crs_list if is_ne)
        unknown_count = sum(1 for crs_str, _ in crs_list if crs_str is None)
        crs_counter = {}
        for crs_str, _ in crs_list:
            if crs_str is not None:
                crs_counter[crs_str] = crs_counter.get(crs_str, 0) + 1
        distinct_crs = len(crs_counter)
        result_is_non_earth = False
        if self._crs is not None:
            result_is_non_earth = CrsReader.is_non_earth(self._crs)
        elif self._out_format not in WGS84_FORMATS:
            result_is_non_earth = (non_earth_count == total and unknown_count == 0)
        if result_is_non_earth and non_earth_count == total and distinct_crs <= 1:
            self.progress.setValue(0)
            return True
        if non_earth_count == 0 and distinct_crs <= 1 and unknown_count == 0:
            self.progress.setValue(0)
            return True
        dialog = CrsWarningDialog(
            self, non_earth_count, total, crs_counter,
            self._out_format, result_is_non_earth, unknown_count
        )
        result = dialog.exec()
        self.progress.setValue(0)
        if result == QDialog.Accepted:
            if non_earth_count > 0:
                if result_is_non_earth:
                    self.log_msg(
                        f"Предупреждение: {non_earth_count} источников "
                        f"в план-схеме (NonEarth), результат — тоже план-схема. "
                        f"Координаты переносятся как есть. Продолжено пользователем."
                    )
                else:
                    self.log_msg(
                        f"Предупреждение: {non_earth_count} источников "
                        f"в план-схеме (NonEarth). Продолжено пользователем."
                    )
            if distinct_crs > 1:
                self.log_msg(
                    f"Предупреждение: {distinct_crs} разных СК среди "
                    f"источников. Продолжено пользователем."
                )
            if unknown_count > 0:
                self.log_msg(
                    f"Предупреждение: {unknown_count} источников "
                    f"с неизвестной СК (нет .prj или других метаданных). "
                    f"Продолжено пользователем."
                )
            return True
        else:
            self.log_msg("Объединение отменено: проблемы с СК исходных данных.")
            return False

    def select_coord_system(self):
        dialog = ChooseCoordSystemDialog(self._crs)
        if dialog.exec() == QDialog.Accepted:
            self._crs = dialog.chosenCoordSystem()
            self._crs_user_override = True
            self.update_crs_display()

    def update_crs_display(self):
        if self._crs is not None:
            self.label_crs_value.setText(self._crs.title)
        else:
            self.label_crs_value.setText("Не задана")

    def _auto_set_crs_for_format(self):
        if self._out_format in WGS84_FORMATS and not self._crs_user_override:
            try:
                self._crs = CoordSystem.from_epsg(4326)
                self.log_msg(
                    f"СК автоматически установлена на EPSG:4326 "
                    f"(требование формата {self._out_format.upper()})"
                )
            except Exception as e:
                self.log_msg(f"Не удалось установить EPSG:4326: {e}")
            self.update_crs_display()

    def update_crs_from_source(self):
        if self._out_format in WGS84_FORMATS:
            return
        self._crs_user_override = False
        use_open = self.chk_open_tables.isChecked()
        try:
            if use_open:
                if self.selected_tables:
                    first = self.selected_tables[0]
                    self._crs = getattr(first, 'coordsystem', None)
                else:
                    self._crs = None
            else:
                src_dir = self.edit_src.text().strip()
                if src_dir and os.path.isdir(src_dir):
                    source_files = self.get_source_files_for_preview(src_dir)
                    if source_files:
                        fmt_key = self.get_source_format_key()
                        self._crs = CrsReader.from_file_fast(source_files[0], fmt_key)
                    else:
                        self._crs = None
                else:
                    self._crs = None
        except Exception:
            self._crs = None
        if self._crs is None:
            self._try_restore_crs()
        self.update_crs_display()

    def on_format_changed(self):
        self.update_crs_from_source()

    def toggle_source_mode(self):
        use_open = self.chk_open_tables.isChecked()
        self.label_src.setEnabled(not use_open)
        self.edit_src.setEnabled(not use_open)
        self.btn_src.setEnabled(not use_open)
        self.label_format.setEnabled(not use_open)
        self.combo_format.setEnabled(not use_open)
        self.btn_select_tables.setEnabled(use_open)
        if use_open:
            self.all_open_tables = [
                t for t in data_manager.tables
                if type(t).__name__ not in (
                    'QueryTable', 'SelectionTable', 'CosmeticTable'
                )
            ]
            self.selected_tables = list(self.all_open_tables)
        else:
            self.selected_tables = []
            self.all_open_tables = []
        self.update_crs_from_source()

    def show_table_selector(self):
        if not self.all_open_tables:
            QMessageBox.information(self, "Открытые таблицы", "Нет открытых таблиц для объединения.")
            return
        table_names = [t.name for t in self.all_open_tables]
        dialog = TableSelectorDialog(self, table_names)
        if dialog.exec():
            indices = dialog.get_selected_indices()
            self.selected_tables = [self.all_open_tables[i] for i in indices]
            self.update_crs_from_source()

    def select_source_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с файлами")
        if folder:
            self.edit_src.setText(folder)
            self.update_crs_from_source()

    def select_output_file(self):
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Сохранить как", "", OUTPUT_FILTERS
        )
        if not path:
            return
        prev_format = self._out_format
        ext = os.path.splitext(path)[1].lstrip('.').lower()
        format_by_ext = EXT_TO_OUTPUT_KEY.get(ext)
        if format_by_ext is not None:
            self._out_format = format_by_ext
        else:
            for key, (_, filt, _) in OUTPUT_FORMATS.items():
                if filt == selected_filter:
                    self._out_format = key
                    break
            out_ext = self.get_output_extension()
            if not path.lower().endswith(f".{out_ext}"):
                path += f".{out_ext}"
        self.edit_out.setText(path)
        if self._out_format != prev_format:
            self._crs_user_override = False
            self._auto_set_crs_for_format()
            if self._out_format not in WGS84_FORMATS:
                self.update_crs_from_source()

    def log_msg(self, msg):
        self.log.append(msg)
        QApplication.processEvents()

    def toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self.btn_pause.setText("Возобновить")
            self.log_msg("---")
            self.log_msg("Пауза. Нажмите 'Возобновить' для продолжения.")
        else:
            self.btn_pause.setText("Пауза")
            self.log_msg("Продолжение объединения...")

    def cancel_merge(self):
        self._cancelled = True
        self._paused = False
        self.log_msg("---")
        self.log_msg("Прерывание... завершаем текущую операцию.")

    def _open_table_safely(self, table, try_as_map=True):
        if not try_as_map:
            try:
                view_manager.create_tableview(table)
            except Exception as e:
                self.log_msg(f"Не удалось открыть таблицу: {e}")
            return
        try:
            layer = Layer.create(table)
            map_ = Map([layer])
            view_manager.create_mapview(map_)
        except Exception as e:
            self.log_msg(f"Не удалось открыть как карту: {e}")
            try:
                view_manager.create_tableview(table)
            except Exception as e2:
                self.log_msg(f"Не удалось открыть таблицу: {e2}")

    def open_result(self, out_file):
        if self._out_format == "mif":
            temp_tab = MergeEngine.mif_to_temp_tab(out_file)
            try:
                table = provider_manager.openfile(temp_tab)
                self._open_table_safely(table)
            except Exception as e:
                self.log_msg(f"Ошибка при открытии таблицы: {e}")
            finally:
                MergeEngine.cleanup_tab_files(temp_tab)
        elif self._out_format == "csv":
            delimiter = SchemaReader.detect_csv_delimiter(out_file)
            table = None
            for attempt in (
                lambda: provider_manager.openfile(out_file, delimiter=delimiter),
                lambda: provider_manager.csv.openfile(out_file, delimiter=delimiter),
                lambda: provider_manager.openfile(out_file),
            ):
                try:
                    table = attempt()
                    break
                except (TypeError, AttributeError):
                    continue
                except Exception as e:
                    self.log_msg(f"Не удалось открыть с разделителем: {e}")
                    continue
            if table is not None:
                self._open_table_safely(table, try_as_map=False)
            else:
                self.log_msg("Не удалось открыть CSV файл.")
        else:
            try:
                table = provider_manager.openfile(out_file)
                self._open_table_safely(table)
            except Exception as e:
                self.log_msg(f"Ошибка при открытии таблицы: {e}")

    def filter_by_reference(self, sources, ref_path, source_ext, use_open):
        ref_schema = self.get_schema_for_file(ref_path)
        if not ref_schema:
            self.log_msg("Ошибка: не удалось прочитать схему эталонного файла.")
            return []
        self.log_msg(f"Эталон: {os.path.basename(ref_path)}")
        self.log_msg(f"Эталонная схема ({len(ref_schema)} колонок): {', '.join(name for name, _ in ref_schema)}")
        total = len(sources)
        self.progress.setVisible(True)
        self.progress.setMaximum(total)
        self.progress.setValue(0)
        self.progress.setFormat("Фильтрация: %p%")
        QApplication.processEvents()
        compatible = []
        for i, source in enumerate(sources):
            try:
                schema = self.get_schema_columns(source, use_open, source_ext)
                if SchemaReader.schemas_match(ref_schema, schema):
                    compatible.append(source)
            except Exception:
                pass
            if (i + 1) % SCHEMA_UI_UPDATE_INTERVAL == 0 or i + 1 == total:
                self.progress.setValue(i + 1)
                QApplication.processEvents()
        self.progress.setFormat("%p%")
        self.progress.setValue(total)
        excluded = total - len(compatible)
        self.log_msg(f"Найдено {len(compatible)} из {total} источников, соответствующих эталону.")
        if excluded:
            self.log_msg(f"Исключено: {excluded} — другая структура.")
        self.log_msg("---")
        return compatible

    def _on_table_closed(self):
        if self.chk_open_tables.isChecked():
            self.all_open_tables = [
                t for t in data_manager.tables
                if type(t).__name__ not in (
                    'QueryTable', 'SelectionTable', 'CosmeticTable'
                )
            ]
            self.selected_tables = list(self.all_open_tables)

    def _set_controls_enabled(self, enabled):
        """Включает/выключает элементы ввода во время объединения."""
        for widget in (
            self.btn_src, self.btn_out, self.btn_crs,
            self.combo_format, self.chk_open_tables,
            self.btn_select_tables, self.edit_src, self.edit_out
        ):
            widget.setEnabled(enabled)

    def run_merge(self):
        if self._is_running:
            return
        self._is_running = True

        # Блокируем все элементы управления на время процесса
        self._set_controls_enabled(False)
        self.btn_run.setText("Идёт объединение...")
        QApplication.processEvents()

        try:
            self._run_merge_impl()
        except Exception as e:
            self.log_msg(f"\nКритическая ошибка: {e}")
            self.log_msg(traceback.format_exc())
        finally:
            self._is_running = False
            self._set_controls_enabled(True)
            self.btn_run.setText("Объединить")
            self.btn_pause.setEnabled(False)
            self.btn_pause.setText("Пауза")
            self.btn_cancel.setEnabled(False)
            self._cancelled = False
            self._paused = False
            self.progress.setVisible(False)

    def _run_merge_impl(self):
        out_file = self.edit_out.text().strip()
        if not out_file:
            self.log_msg("Ошибка: укажите путь к результирующему файлу.")
            return
        prev_format = self._out_format
        ext = os.path.splitext(out_file)[1].lstrip('.').lower()
        format_by_ext = EXT_TO_OUTPUT_KEY.get(ext)
        if format_by_ext is not None:
            self._out_format = format_by_ext
        out_ext = self.get_output_extension()
        if not out_file.lower().endswith(f".{out_ext}"):
            out_file += f".{out_ext}"
        if self._out_format != prev_format:
            self._crs_user_override = False
            self._auto_set_crs_for_format()
            if self._out_format not in WGS84_FORMATS:
                self.update_crs_from_source()
        if not self._output_guard.ensure_not_open(out_file, on_table_closed=self._on_table_closed):
            return
        use_open = self.chk_open_tables.isChecked()
        if use_open:
            if not self.selected_tables:
                self.log_msg("Ошибка: не выбраны таблицы для объединения.")
                return
            out_file_norm = os.path.normpath(out_file).lower()
            sources = [
                t for t in self.selected_tables
                if not (getattr(t, 'file_name', None) and os.path.normpath(t.file_name).lower() == out_file_norm)
            ]
            if not sources:
                self.log_msg("Нет таблиц для объединения.")
                return
            total_count = len(sources)
        else:
            src_dir = self.edit_src.text().strip()
            if not src_dir or not os.path.isdir(src_dir):
                self.log_msg("Ошибка: укажите существующую исходную папку.")
                return
            fmt_key = self.get_source_format_key()
            if fmt_key == "mif":
                with_mid, without_mid = self.collect_mif_files(src_dir)
                if not with_mid and not without_mid:
                    self.log_msg("В папке не найдено .mif-файлов.")
                    return
                if without_mid:
                    dialog = MidMissingDialog(self, with_mid, without_mid)
                    result = dialog.exec()
                    if result == 0:
                        self.log_msg("Операция отменена пользователем.")
                        return
                    elif result == 1:
                        source_files = sorted(with_mid + without_mid)
                        self.log_msg(f"Включены .mif без .mid: {len(without_mid)} файл(ов). Атрибуты могут быть пустыми.")
                    elif result == 2:
                        source_files = with_mid
                        if not source_files:
                            self.log_msg("Нет .mif-файлов с парным .mid.")
                            return
                        self.log_msg(f"Файлы без .mid пропущены: {len(without_mid)}")
                else:
                    source_files = with_mid
            else:
                source_files = self.collect_source_files(src_dir)
                if not source_files:
                    ext_list = INPUT_FORMATS[fmt_key][0]
                    ext_str = ", ".join(f".{e}" for e in ext_list)
                    self.log_msg(f"В папке не найдено файлов ({ext_str}).")
                    return
            out_file_norm = os.path.normpath(out_file).lower()
            source_files = [f for f in source_files if os.path.normpath(f).lower() != out_file_norm]
            if not source_files:
                self.log_msg("Нет файлов для объединения.")
                return
            sources = source_files
            total_count = len(source_files)
        source_ext = self.get_source_format_key() if not use_open else None
        ref_schema_for_export = None
        # Проверка схем
        if total_count > 1:
            self.progress.setVisible(True)
            self.progress.setMaximum(total_count)
            self.progress.setValue(0)
            self.progress.setFormat("Проверка схем: %p%")
            QApplication.processEvents()
            ref_schema = self.get_schema_columns(sources[0], use_open, source_ext)
            if not ref_schema:
                self.log_msg("Предупреждение: не удалось прочитать эталонную схему. Проверка пропущена.")
            else:
                self.log_msg(f"Эталонная схема ({len(ref_schema)} колонок): {', '.join(name for name, _ in ref_schema)}")
                mismatched_count = 0
                compatible = [sources[0]]
                for i in range(1, len(sources)):
                    source = sources[i]
                    try:
                        schema = self.get_schema_columns(source, use_open, source_ext)
                        if SchemaReader.schemas_match(ref_schema, schema):
                            compatible.append(source)
                        else:
                            mismatched_count += 1
                    except Exception:
                        mismatched_count += 1
                    if (i + 1) % SCHEMA_UI_UPDATE_INTERVAL == 0 or i + 1 == total_count:
                        self.progress.setValue(i + 1)
                        QApplication.processEvents()
                self.progress.setFormat("%p%")
                self.progress.setValue(total_count)
                if mismatched_count > 0:
                    if not use_open:
                        src_dir_for_dialog = self.edit_src.text().strip()
                        input_filter = INPUT_FORMATS[self.get_source_format_key()][1]
                    else:
                        src_dir_for_dialog = ""
                        input_filter = ""
                    if use_open:
                        default_ref_name = sources[0].name
                    else:
                        default_ref_name = os.path.basename(sources[0])
                    dialog = SchemaMismatchDialog(
                        self, total_count, len(compatible),
                        src_dir_for_dialog, input_filter,
                        default_ref_name
                    )
                    choice = dialog.exec()
                    if choice == 0:
                        self.log_msg("Объединение отменено: несовместимые схемы.")
                        self.progress.setVisible(False)
                        return
                    elif choice == 1:
                        self.log_msg("Объединение всех источников (с расхождениями).")
                        self.log_msg("---")
                    elif choice == 3:
                        ref_path = dialog.get_reference_path()
                        if dialog.is_reference_changed() and ref_path:
                            sources = self.filter_by_reference(sources, ref_path, source_ext, use_open)
                            ref_schema_for_export = ref_path
                        else:
                            sources = compatible
                        if not sources:
                            self.log_msg("Нет источников, соответствующих эталону.")
                            self.progress.setVisible(False)
                            return
                        total_count = len(sources)
                else:
                    self.log_msg(f"Проверка схем: все {total_count} источников совместимы.")
                    self.log_msg("---")
            self.progress.setValue(0)
        # Проверка СК
        if not self._check_crs(sources, use_open, source_ext):
            self.progress.setVisible(False)
            return
        # Проверка блокировки выхода
        is_open, _, _ = self._output_guard.is_file_open(out_file)
        if is_open:
            if not self._output_guard.ensure_not_open(out_file, on_table_closed=self._on_table_closed):
                return
        time.sleep(0.3)
        # Запуск слияния
        self._cancelled = False
        self._paused = False
        self.log_msg("=" * 60)
        self.log_msg(f"Режим: {'открытые таблицы' if use_open else 'файлы из папки'}")
        if not use_open:
            self.log_msg(f"Формат источников: {self.get_source_format_key()}")
        if ref_schema_for_export:
            self.log_msg(f"Эталон: {os.path.basename(ref_schema_for_export)}")
        self.log_msg(f"Формат результата: .{out_ext}")
        self.log_msg(f"Количество источников: {total_count}")
        if self._crs is not None:
            self.log_msg(f"СК результата: {self._crs.title}")
        else:
            self.log_msg("СК результата: не задана")
        self.log_msg("---")
        self.progress.setMaximum(total_count)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.btn_run.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("Пауза")
        self.btn_cancel.setEnabled(True)
        t_start = time.time()

        def on_pause_check():
            while self._paused and not self._cancelled:
                QApplication.processEvents()
                time.sleep(0.1)
            return self._cancelled

        def on_cancel_check():
            return self._cancelled

        def progress_callback(val):
            self.progress.setValue(val)
            QApplication.processEvents()

        engine = MergeEngine(
            self._out_format, self._crs,
            log_callback=self.log_msg,
            progress_callback=progress_callback
        )
        try:
            stats = engine.run(
                sources, use_open, source_ext, out_file,
                ref_schema_for_export=ref_schema_for_export,
                on_pause_check=on_pause_check,
                on_cancel_check=on_cancel_check
            )
            elapsed_total = time.time() - t_start
            mins = int(elapsed_total // 60)
            secs = int(elapsed_total % 60)
            self.log_msg("---")
            if self._cancelled:
                self.log_msg("Процесс прерван пользователем.")
            else:
                self.log_msg("Готово!")
            self.log_msg(f"Источников всего: {total_count}")
            self.log_msg(f"Успешно обработано: {stats['files_processed']}")
            if stats['failed_sources']:
                self.log_msg(
                    f"С ошибками: {len(stats['failed_sources'])} "
                    f"({', '.join(stats['failed_sources'])})"
                )
            self.log_msg(f"Пустых источников: {stats['empty_sources']}")
            self.log_msg(f"Всего записей: {stats['total']:,}")
            self.log_msg(f"Записей отдано генератором: {stats['total_yielded']:,}")
            if stats['total'] != stats['total_yielded']:
                self.log_msg(
                    f"⚠ Расхождение: экспортировано {stats['total']:,}, "
                    f"генератором {stats['total_yielded']:,}"
                )
            self.log_msg(f"Затрачено: {mins} мин {secs} с")
            self.log_msg(f"Результат: {out_file}")
            Notifications.push(
                "Объединение таблиц",
                f"{'Прервано' if self._cancelled else 'Объединено'}: "
                f"{stats['files_processed']} источников, "
                f"{stats['total']:,} записей за {mins} мин {secs} с."
            )
            if not self._cancelled:
                msg_box = QMessageBox(self)
                msg_box.setWindowTitle("Результат объединения")
                msg_box.setIcon(QMessageBox.Question)
                msg_box.setText(f"Операция завершена успешно.\nОткрыть таблицу {os.path.basename(out_file)}?")
                msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
                msg_box.setDefaultButton(QMessageBox.Yes)
                msg_box.button(QMessageBox.Yes).setText("Да")
                msg_box.button(QMessageBox.No).setText("Нет")
                if msg_box.exec() == QMessageBox.Yes:
                    try:
                        self.open_result(out_file)
                    except Exception as e:
                        self.log_msg(f"Ошибка при открытии таблицы: {e}")
        except Exception as e:
            self.log_msg(f"\nКритическая ошибка: {e}")
            self.log_msg(traceback.format_exc())
        finally:
            self.btn_run.setEnabled(True)
            self.btn_pause.setEnabled(False)
            self.btn_pause.setText("Пауза")
            self.btn_cancel.setEnabled(False)
            self._cancelled = False
            self._paused = False

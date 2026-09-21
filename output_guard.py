"""
Модуль проверки блокировок выходных файлов.

OutputGuard — экземпляр, создаётся MergeDialog.
Зависимости: constants (OUTPUT_COMPANION_EXTS), axipy (view_manager, data_manager),
             PySide2 (QMessageBox, QApplication), os, time.
"""

import os
import time

from PySide2.QtWidgets import QMessageBox, QApplication

from axipy import view_manager, data_manager

from .constants import OUTPUT_COMPANION_EXTS


class OutputGuard:
    """Проверка и снятие блокировок выходных файлов.

    Создаётся MergeDialog. Принимает log_callback и опционально parent
    (виджет-родитель для QMessageBox).
    """

    # Приоритетные атрибуты для поиска пути файла таблицы
    _PATH_ATTRS = ('file_name', 'fileName', 'file', 'path', 'filepath', 'file_path')

    def __init__(self, log_callback=None, parent=None):
        self._log = log_callback or (lambda msg: None)
        self._parent = parent
        # Кэш путей файлов таблиц. Ключ — id(obj), безопасно пока таблицы
        # удерживаются data_manager.tables.
        self._file_path_cache = {}
        self._views_attr = None

    def clear_cache(self):
        """Очистка кэша путей файлов."""
        self._file_path_cache.clear()

    def _get_companion_files(self, out_file):
        ext = os.path.splitext(out_file)[1].lstrip('.').lower()
        base = os.path.splitext(out_file)[0]
        exts = OUTPUT_COMPANION_EXTS.get(ext, ['.' + ext])
        return [base + e for e in exts]

    def _is_file_locked(self, filepath):
        if not os.path.exists(filepath):
            return False
        temp_name = filepath + '.__lockcheck_tmp__'
        try:
            os.rename(filepath, temp_name)
            os.rename(temp_name, filepath)
            return False
        except (PermissionError, OSError):
            return True

    def _get_all_views(self):
        if self._views_attr is None:
            for attr in ('views', 'all_views', 'view_list'):
                if getattr(view_manager, attr, None) is not None:
                    self._views_attr = attr
                    break
        if self._views_attr is None:
            return []
        try:
            return list(getattr(view_manager, self._views_attr))
        except Exception:
            return []

    def _extract_file_path(self, obj):
        obj_id = id(obj)
        if obj_id in self._file_path_cache:
            return self._file_path_cache[obj_id]

        # Сначала проверяем приоритетные атрибуты — быстро
        for attr_name in self._PATH_ATTRS:
            try:
                val = getattr(obj, attr_name)
                if isinstance(val, str) and os.path.isfile(val):
                    self._file_path_cache[obj_id] = val
                    return val
            except Exception:
                continue

        # Фолбэк: полный перебор через dir()
        for attr_name in dir(obj):
            if attr_name.startswith('_'):
                continue
            if attr_name in self._PATH_ATTRS:
                continue  # Уже проверили
            try:
                val = getattr(obj, attr_name)
            except Exception:
                continue
            if isinstance(val, str) and os.path.isfile(val):
                self._file_path_cache[obj_id] = val
                return val
        self._file_path_cache[obj_id] = None
        return None

    def _find_table_by_path(self, out_file):
        out_norm = os.path.normpath(out_file).lower()
        for t in data_manager.tables:
            t_type = type(t).__name__
            if t_type in ('QueryTable', 'SelectionTable', 'CosmeticTable'):
                continue
            path = self._extract_file_path(t)
            if path and os.path.normpath(path).lower() == out_norm:
                return t
        return None

    def _name_matches(self, t_name, out_basename):
        t_name = t_name.lower()
        if t_name == out_basename or t_name == '_' + out_basename:
            return True
        for prefix in (out_basename, '_' + out_basename):
            if t_name.startswith(prefix):
                suffix = t_name[len(prefix):].lstrip('_')
                if suffix and suffix.isdigit():
                    return True
        return False

    def _find_table_by_name(self, out_file):
        out_basename = os.path.splitext(os.path.basename(out_file))[0].lower()
        for t in data_manager.tables:
            t_type = type(t).__name__
            if t_type in ('QueryTable', 'SelectionTable', 'CosmeticTable'):
                continue
            if self._name_matches(t.name, out_basename):
                return t
        return None

    def _find_table_in_views(self, out_file):
        out_norm = os.path.normpath(out_file).lower()
        out_basename = os.path.splitext(os.path.basename(out_file))[0].lower()

        for view in self._get_all_views():
            try:
                view_map = getattr(view, 'map', None)
                if view_map is None:
                    continue
                layers = getattr(view_map, 'layers', None)
                if layers is None:
                    continue
                for layer in layers:
                    try:
                        layer_table = getattr(layer, 'table', None)
                    except Exception:
                        continue
                    if layer_table is None:
                        continue

                    path = self._extract_file_path(layer_table)
                    if path and os.path.normpath(path).lower() == out_norm:
                        return layer_table, view

                    try:
                        if self._name_matches(layer_table.name, out_basename):
                            return layer_table, view
                    except Exception:
                        pass
            except Exception:
                pass

        return None, None

    def is_file_open(self, out_file):
        """Проверка, открыт ли файл в Аксиоме.

        Возвращает (is_open, name, table | None).
        """
        companion_files = self._get_companion_files(out_file)
        any_locked = any(
            self._is_file_locked(cf)
            for cf in companion_files
            if os.path.exists(cf)
        )

        t = self._find_table_by_path(out_file)
        if t is not None:
            return True, t.name, t

        t = self._find_table_by_name(out_file)
        if t is not None:
            return True, t.name, t

        t_in_view, view_obj = self._find_table_in_views(out_file)
        if t_in_view is not None:
            return True, t_in_view.name, t_in_view

        if any_locked:
            return True, os.path.basename(out_file), None

        return False, None, None

    def close_table(self, table_obj):
        """Закрытие таблицы: из видов и из data_manager.

        Возвращает True, если таблица больше не в data_manager.tables.
        """
        for view in self._get_all_views():
            try:
                view_table = getattr(view, 'table', None)
                if view_table is table_obj:
                    view.close()
                    continue

                view_map = getattr(view, 'map', None)
                if view_map is not None:
                    layers = getattr(view_map, 'layers', None)
                    if layers is not None:
                        for layer in layers:
                            layer_table = getattr(layer, 'table', None)
                            if layer_table is table_obj:
                                view.close()
                                break
            except Exception:
                pass

        try:
            table_obj.close()
        except Exception as e:
            self._log(f"Предупреждение при закрытии таблицы: {e}")

        return table_obj not in data_manager.tables

    def ensure_not_open(self, out_file, on_table_closed=None):
        """Интерактивный цикл: убедиться, что выходной файл не заблокирован.

        Возвращает True, если файл свободен, False — если пользователь отменил.
        on_table_closed — опциональный коллбэк, вызывается после успешного
        закрытия таблицы (используется MergeDialog для обновления списков).
        """
        self._file_path_cache.clear()

        while True:
            is_open, open_name, open_table = self.is_file_open(out_file)
            if not is_open:
                return True

            if open_table is None:
                self._log("--- Диагностика блокировки ---")
                self._log(f"Выходной файл: {out_file}")
                self._log(f"Companion files: {self._get_companion_files(out_file)}")
                open_tables = [
                    t for t in data_manager.tables
                    if type(t).__name__ not in (
                        'QueryTable', 'SelectionTable', 'CosmeticTable'
                    )
                ]
                self._log(f"Открытых таблиц: {len(open_tables)}")
                for t in open_tables:
                    t_type = type(t).__name__
                    t_name = getattr(t, 'name', '???')
                    path = self._extract_file_path(t)
                    self._log(f"  [{t_type}] name='{t_name}' path='{path}'")
                self._log("--- Конец диагностики ---")

            msg_box = QMessageBox(self._parent)
            msg_box.setWindowTitle("Файл занят")
            msg_box.setIcon(QMessageBox.Warning)
            if open_table is not None:
                msg_text = (
                    f"Файл «{os.path.basename(out_file)}» открыт в Аксиоме "
                    f"как таблица «{open_name}».\n\n"
                    f"Закройте эту таблицу или выберите другое имя файла."
                )
            else:
                msg_text = (
                    f"Файл «{os.path.basename(out_file)}» заблокирован.\n\n"
                    f"Возможно, он открыт в Аксиоме или другой программе.\n"
                    f"Закройте его или выберите другое имя файла."
                )
            msg_box.setText(msg_text)

            btn_close = msg_box.addButton("Закрыть таблицу", QMessageBox.AcceptRole)
            btn_cancel = msg_box.addButton("Отмена", QMessageBox.RejectRole)
            msg_box.setDefaultButton(btn_close)
            msg_box.exec()

            if msg_box.clickedButton() == btn_cancel:
                self._log("Объединение отменено: результирующий файл занят.")
                return False

            if open_table is not None:
                self._log(f"Попытка закрыть таблицу «{open_name}»...")
                QApplication.processEvents()

                if self.close_table(open_table):
                    self._log(f"Таблица «{open_name}» закрыта.")
                    if on_table_closed is not None:
                        on_table_closed()
                    self._file_path_cache.clear()
                    time.sleep(0.5)
                else:
                    self._log(
                        f"Не удалось закрыть «{open_name}» программно. "
                        f"Закройте таблицу вручную и нажмите «Закрыть таблицу» снова."
                    )
                    QMessageBox.information(
                        self._parent,
                        "Не удалось закрыть",
                        f"Не удалось закрыть таблицу «{open_name}» программно.\n\n"
                        f"Закройте её вручную в Аксиоме, затем нажмите "
                        f"«Закрыть таблицу» снова.",
                        QMessageBox.Ok
                    )
            else:
                self._log(
                    "Таблица не найдена в API. "
                    "Закройте файл вручную в Аксиоме."
                )
                QMessageBox.information(
                    self._parent,
                    "Закройте вручную",
                    f"Программа не смогла найти таблицу «{open_name}» "
                    f"в списке открытых и закрыть её автоматически.\n\n"
                    f"Закройте таблицу вручную в Аксиоме "
                    f"(правой кнопкой → Закрыть),\n"
                    f"затем нажмите «ОК» для повторной проверки.",
                    QMessageBox.Ok
                )

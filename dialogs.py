"""
Диалоговые классы плагина «Мастер объединения ГИС-данных».
Перенесены без изменений из монолитного __init__.py.
"""

import os

from PySide2.QtWidgets import (
    QDialog, QPushButton, QLabel,
    QVBoxLayout, QHBoxLayout, QFileDialog,
    QListWidget
)
from PySide2.QtCore import Qt

from .constants import WGS84_FORMATS


class TableSelectorDialog(QDialog):
    """Диалог выбора открытых таблиц для объединения."""

    def __init__(self, parent, table_names):
        super().__init__(parent)
        self.setWindowTitle("Выбор таблиц для объединения")
        self.resize(400, 350)

        self.list_tables = QListWidget()
        self.list_tables.setSelectionMode(QListWidget.ExtendedSelection)
        for name in table_names:
            self.list_tables.addItem(name)
        self.list_tables.selectAll()

        btn_select_all = QPushButton("Выделить все")
        btn_select_all.clicked.connect(self.list_tables.selectAll)
        btn_deselect_all = QPushButton("Снять выделение")
        btn_deselect_all.clicked.connect(self.list_tables.clearSelection)

        btn_top = QHBoxLayout()
        btn_top.addWidget(btn_select_all)
        btn_top.addWidget(btn_deselect_all)
        btn_top.addStretch()

        btn_ok = QPushButton("ОК")
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_bottom = QHBoxLayout()
        btn_bottom.addStretch()
        btn_bottom.addWidget(btn_ok)
        btn_bottom.addWidget(btn_cancel)

        layout = QVBoxLayout()
        layout.addLayout(btn_top)
        layout.addWidget(self.list_tables)
        layout.addLayout(btn_bottom)
        self.setLayout(layout)

    def get_selected_indices(self):
        return [
            self.list_tables.row(item)
            for item in self.list_tables.selectedItems()
        ]


class MidMissingDialog(QDialog):
    """Диалог выбора действия при отсутствии .mid-файлов."""

    def __init__(self, parent, with_mid, without_mid):
        super().__init__(parent)
        self.setWindowTitle("Отсутствуют .mid-файлы")
        self.resize(450, 300)

        label = QLabel(
            f"Найдено .mif-файлов: {len(with_mid) + len(without_mid)}\n"
            f"С парным .mid: {len(with_mid)}\n"
            f"Без .mid: {len(without_mid)}\n\n"
            f"Файлы без .mid:\n"
            f"{'-' * 40}\n"
            f"{chr(10).join(os.path.basename(f) for f in without_mid[:20])}"
        )
        if len(without_mid) > 20:
            label.setText(label.text() + f"\n... и ещё {len(without_mid) - 20} файл(ов)")

        label.setWordWrap(True)

        btn_all = QPushButton("Продолжить со всеми")
        btn_all.setToolTip("Попытаться конвертировать все .mif, включая без .mid")
        btn_all.clicked.connect(lambda: self.done(1))

        btn_only_mid = QPushButton("Только с парным .mid")
        btn_only_mid.setToolTip("Объединять только файлы, у которых есть .mid")
        btn_only_mid.clicked.connect(lambda: self.done(2))

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_only_mid)
        btn_layout.addWidget(btn_cancel)

        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addLayout(btn_layout)
        self.setLayout(layout)


class SchemaMismatchDialog(QDialog):
    """Диалог предупреждения о несовпадении схем источников.

    Возвращаемые коды:
      0 — Отмена
      1 — Продолжить со всеми
      3 — Объединить по эталону
    """

    def __init__(self, parent, total_count, compatible_count,
                 source_dir, input_filter,
                 default_ref_name):
        super().__init__(parent)
        self.setWindowTitle("Несовпадение схем")
        self.resize(500, 250)
        self._source_dir = source_dir
        self._input_filter = input_filter
        self._ref_changed = False
        self._selected_ref = None

        incompatible_count = total_count - compatible_count

        summary = QLabel(
            f"Проверено источников: {total_count}\n"
            f"Совместимых: {compatible_count}\n"
            f"С расхождениями: {incompatible_count}"
        )
        summary.setStyleSheet("font-weight: bold;")

        warning = QLabel(
            "⚠ Обнаружены таблицы, схема которых не совпадает "
            "с остальными источниками."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #cc6600;")

        hint = QLabel(
            "Можно объединить только совместимые таблицы "
            "(выбрать эталон) или все вместе."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555; font-style: italic;")

        self.label_ref_name = QLabel(default_ref_name)
        self.label_ref_name.setStyleSheet("color: black; font-weight: bold;")
        self.btn_ref = QPushButton("Выбрать эталон...")
        self.btn_ref.clicked.connect(self.choose_reference)

        ref_layout = QHBoxLayout()
        ref_layout.addWidget(self.btn_ref)
        ref_layout.addWidget(self.label_ref_name, 1)

        self.btn_merge_ref = QPushButton("Объединить по эталону")
        self.btn_merge_ref.setToolTip(
            "Объединить только источники, схема которых совпадает с эталоном"
        )
        self.btn_merge_ref.clicked.connect(lambda: self.done(3))

        btn_all = QPushButton("Продолжить со всеми")
        btn_all.setToolTip("Объединить все источники, несмотря на расхождения")
        btn_all.clicked.connect(lambda: self.done(1))

        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.btn_merge_ref)
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_cancel)

        layout = QVBoxLayout()
        layout.addWidget(summary)
        layout.addWidget(warning)
        layout.addWidget(hint)
        layout.addLayout(ref_layout)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите эталонный файл",
            self._source_dir,
            f"{self._input_filter};;All files (*.*)"
        )
        if path:
            self._selected_ref = path
            self._ref_changed = True
            self.label_ref_name.setText(os.path.basename(path))

    def get_reference_path(self):
        return self._selected_ref

    def is_reference_changed(self):
        return self._ref_changed


class CrsWarningDialog(QDialog):
    """Компактный диалог предупреждения о проблемах с СК."""

    def __init__(self, parent, non_earth_count, total_count, crs_counter,
                 out_format, result_is_non_earth=False, unknown_count=0):
        super().__init__(parent)
        self.setWindowTitle("Предупреждение: СК")
        self.setMinimumWidth(420)
        self.setMaximumWidth(520)

        icon_label = QLabel("⚠")
        icon_label.setStyleSheet("font-size: 28px; color: #cc6600;")
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignCenter)

        self.warning_text = QLabel()
        self.warning_text.setWordWrap(True)

        self.details_text = QLabel()
        self.details_text.setWordWrap(True)
        self.details_text.setStyleSheet(
            "color: #666; font-size: 11px; margin-top: 6px; margin-left: 44px;"
        )
        self.details_text.setVisible(False)

        btn_details = QPushButton("Подробнее ▾")
        btn_details.setCheckable(True)
        btn_details.setStyleSheet(
            "text-align: left; border: none; color: #0066cc; padding-left: 44px;"
        )

        def toggle_details(checked):
            self.details_text.setVisible(checked)
            btn_details.setText("Скрыть ▴" if checked else "Подробнее ▾")
            self.adjustSize()

        btn_details.toggled.connect(toggle_details)

        warnings = []

        if unknown_count > 0:
            if unknown_count == total_count:
                warnings.append(
                    f"<b style='color:#cc6600'>У всех {total_count} источников "
                    f"не удалось определить СК (например, SHP без файла .prj).<br>"
                    f"Убедитесь, что все источники в одинаковой системе координат.</b>"
                )
            else:
                warnings.append(
                    f"<b style='color:#cc6600'>{unknown_count} из {total_count} "
                    f"источников без определённой СК (например, SHP без .prj).<br>"
                    f"Убедитесь, что эти источники совместимы с остальными.</b>"
                )

        if non_earth_count > 0 and not result_is_non_earth:
            if out_format in WGS84_FORMATS:
                warnings.append(
                    f"<b style='color:#cc0000'>{non_earth_count} из {total_count} "
                    f"источников в план-схеме (NonEarth).<br>"
                    f"Экспорт в {out_format.upper()} требует WGS84 — "
                    f"координаты будут некорректными.</b>"
                )
            else:
                warnings.append(
                    f"<b style='color:#cc0000'>{non_earth_count} из {total_count} "
                    f"источников в план-схеме (NonEarth).<br>"
                    f"Результирующая СК требует пересчёта, "
                    f"что невозможно для план-схемы.</b>"
                )
        elif non_earth_count > 0 and result_is_non_earth:
            if non_earth_count == total_count:
                warnings.append(
                    f"<span style='color:#555'>Все {total_count} источников "
                    f"и результат — план-схема (NonEarth).<br>"
                    f"Координаты переносятся как есть, без пересчёта.</span>"
                )
            else:
                warnings.append(
                    f"<b style='color:#cc6600'>{non_earth_count} из {total_count} "
                    f"источников в план-схеме (NonEarth).<br>"
                    f"Результат тоже план-схема — координаты этих источников "
                    f"переносятся как есть.</b>"
                )

        if non_earth_count == total_count and total_count > 1 and not result_is_non_earth:
            warnings.append(
                f"<span style='color:#555'>Все источники в план-схеме. "
                f"Если они относятся к разным реальным СК, результат "
                f"будет некорректным.</span>"
            )

        distinct = len(crs_counter)
        if distinct > 1:
            warnings.append(
                f"<b style='color:#cc6600'>Обнаружено {distinct} разных СК.</b>"
            )
            lines = []
            for crs_name, count in list(crs_counter.items())[:10]:
                display = crs_name if len(crs_name) <= 70 else crs_name[:67] + '...'
                lines.append(f"  • {display} ({count} ист.)")
            if distinct > 10:
                lines.append(f"  ... и ещё {distinct - 10}")
            if unknown_count > 0:
                lines.append(f"  • СК не определена ({unknown_count} ист.)")
            self.details_text.setText('\n'.join(lines))
            btn_details.setVisible(True)
        elif unknown_count > 0:
            lines = [f"  • СК не определена ({unknown_count} ист.)"]
            for crs_name, count in list(crs_counter.items())[:10]:
                display = crs_name if len(crs_name) <= 70 else crs_name[:67] + '...'
                lines.append(f"  • {display} ({count} ист.)")
            self.details_text.setText('\n'.join(lines))
            btn_details.setVisible(True)
        else:
            btn_details.setVisible(False)

        self.warning_text.setText("<br>".join(warnings))

        btn_continue = QPushButton("Продолжить")
        btn_cancel = QPushButton("Отмена")
        btn_continue.setMinimumHeight(32)
        btn_cancel.setMinimumHeight(32)
        btn_continue.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_continue)

        top_layout = QHBoxLayout()
        top_layout.addWidget(icon_label)
        top_layout.addSpacing(4)
        top_layout.addWidget(self.warning_text, 1)

        layout = QVBoxLayout()
        layout.addLayout(top_layout)
        layout.addWidget(btn_details)
        layout.addWidget(self.details_text)
        layout.addSpacing(4)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

        self.adjustSize()

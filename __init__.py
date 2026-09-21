"""
Плагин «Мастер объединения ГИС-данных» для ГИС Аксиома.
Точка входа — класс MergeTablesPlugin.
"""

from axipy import Plugin, Position, view_manager, ActionManager

from .merge_dialog import MergeDialog


class MergeTablesPlugin(Plugin):
    """Точка входа плагина: регистрация в меню и запуск диалога."""

    def __init__(self):
        self._title = self.tr("Объединение таблиц")
        self._action = self.create_action(
            "Объединить таблицы",
            icon=ActionManager.icon_by_name("merge"),
            on_click=self.show_dialog,
        )
        position = Position("Дополнительно", "Команды")
        position.add(self._action)

    def unload(self):
        self._action.remove()

    def show_dialog(self):
        if hasattr(self, '_merge_dialog') and self._merge_dialog.isVisible():
            self._merge_dialog.raise_()
            self._merge_dialog.activateWindow()
            return
        self._merge_dialog = MergeDialog(view_manager.global_parent)
        self._merge_dialog.show()


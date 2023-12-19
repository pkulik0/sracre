import sys
import deepl
from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget,
                             QPushButton, QWidget, QHBoxLayout,
                             QListWidgetItem, QVBoxLayout, QCheckBox,
                             QComboBox, QLabel, QScrollArea, QGroupBox, QMessageBox)
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent

ICON_SIZE = 128
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')
DEEPL_KEY = ""

translator = deepl.Translator(DEEPL_KEY)


class MainList(QWidget):
    def __init__(self):
        super().__init__()
        self.text_list = []

        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)

        self.setAcceptDrops(True)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.main_layout.addWidget(self.list_widget)

        self.buttons_layout = QHBoxLayout()
        self.main_layout.addLayout(self.buttons_layout)

        self.move_buttons_layout = QVBoxLayout()
        self.buttons_layout.addLayout(self.move_buttons_layout, 2)

        self.up_button = QPushButton("Move Up")
        self.up_button.clicked.connect(self.move_up)
        self.move_buttons_layout.addWidget(self.up_button)

        self.down_button = QPushButton("Move Down")
        self.down_button.clicked.connect(self.move_down)
        self.move_buttons_layout.addWidget(self.down_button)

        self.util_buttons_layout = QVBoxLayout()
        self.buttons_layout.addLayout(self.util_buttons_layout)

        self.remove_button = QPushButton("Remove Item")
        self.remove_button.clicked.connect(self.remove_item)
        self.util_buttons_layout.addWidget(self.remove_button)

        self.clear_button = QPushButton("Clear List")
        self.clear_button.clicked.connect(self.clear_with_confirm)
        self.util_buttons_layout.addWidget(self.clear_button)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.txt'):
                self.load_text(path)
            elif path.lower().endswith(IMAGE_EXT):
                self.add_image(path)

    def add_image(self, path):
        pixmap = QPixmap(path)
        icon = QIcon(pixmap)
        item = QListWidgetItem(icon, self.get_next_text())
        self.list_widget.addItem(item)

    def get_next_text(self):
        return self.text_list.pop() if self.text_list else "???"

    def load_text(self, path):
        with open(path, 'r') as file:
            self.text_list.extend(line.strip() for line in file if line.strip())
            self.text_list.reverse()
            self.update_text()

    def update_text(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setText("???")
        for i in range(min(self.list_widget.count(), len(self.text_list))):
            self.list_widget.item(i).setText(self.get_next_text())

    def remove_item(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def move_up(self):
        for item in self.list_widget.selectedItems():
            row = self.list_widget.row(item)
            if row > 0:
                self.list_widget.takeItem(row)
                self.list_widget.insertItem(row - 1, item)
                self.list_widget.setCurrentItem(item)

    def move_down(self):
        for item in self.list_widget.selectedItems():
            row = self.list_widget.row(item)
            if row < self.list_widget.count() - 1:
                self.list_widget.takeItem(row)
                self.list_widget.insertItem(row + 1, item)
                self.list_widget.setCurrentItem(item)

    def clear_with_confirm(self):
        if self.list_widget.count() > 0:
            if QMessageBox.question(self, "Confirm Clear", "Are you sure you want to clear the list?",
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                self.list_widget.clear()


class LanguagesList(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.checkboxes = []
        self.setLayout(self.layout)

        self.combo_label = QLabel("Source:")
        self.layout.addWidget(self.combo_label)

        self.source_langs = [lang.name for lang in translator.get_source_languages()]
        self.source_langs.sort()
        self.source_langs.insert(0, "???")

        self.source_combo = QComboBox()
        self.source_combo.addItems(self.source_langs)
        self.layout.addWidget(self.source_combo)

        self.target_label = QLabel("Target:")
        self.layout.addWidget(self.target_label)

        self.scrollable_area = QScrollArea(self)
        self.scrollable_area.setWidgetResizable(True)
        self.layout.addWidget(self.scrollable_area)
        self.scrollable_widget = QWidget(self.scrollable_area)
        self.scrollable_layout = QVBoxLayout(self.scrollable_widget)
        self.scrollable_widget.setLayout(self.scrollable_layout)
        self.scrollable_area.setWidget(self.scrollable_widget)

        self.target_langs = [lang.name for lang in translator.get_target_languages()]
        self.target_langs.sort()
        for lang in self.target_langs:
            checkbox = QCheckBox(lang)
            self.checkboxes.append(checkbox)
            self.scrollable_layout.addWidget(checkbox)

    def get_checked(self):
        return [checkbox.text() for checkbox in self.checkboxes if checkbox.isChecked()]

    def get_unchecked(self):
        return [checkbox.text() for checkbox in self.checkboxes if not checkbox.isChecked()]


class SracreWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("sracre")
        self.resize(1000, 600)

        self.main_widget = QWidget()
        self.main_layout = QHBoxLayout()
        self.main_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.main_widget)

        self.list_group = QGroupBox("Content")
        self.list_group_layout = QVBoxLayout()
        self.list_group.setLayout(self.list_group_layout)
        self.main_layout.addWidget(self.list_group, 2)

        self.list_widget = MainList()
        self.list_group_layout.addWidget(self.list_widget)

        self.language_group = QGroupBox("Languages")
        self.language_group_layout = QVBoxLayout()
        self.language_group.setLayout(self.language_group_layout)
        self.main_layout.addWidget(self.language_group)

        self.languages_widget = LanguagesList()
        self.language_group_layout.addWidget(self.languages_widget)

        self.show()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = SracreWindow()
    sys.exit(app.exec())

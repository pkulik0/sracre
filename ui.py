import sys
import deepl
from PyQt6.QtWidgets import QApplication, QMainWindow, QListWidget, QPushButton, QWidget, QHBoxLayout, QListWidgetItem, QVBoxLayout, QCheckBox
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent

ICON_SIZE = 128
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')


class ImageListWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.text_list = []

        self.setWindowTitle("sracre")
        self.resize(1000, 600)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        self.main_layout = QVBoxLayout(central_widget)

        self.list_widget = QListWidget()
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.main_layout.addWidget(self.list_widget)

        self.buttons_layout = QHBoxLayout()
        self.buttons_layout.setContentsMargins(100, 0, 100, 0)
        self.main_layout.addLayout(self.buttons_layout)

        self.up_button = QPushButton("Up")
        self.up_button.clicked.connect(self.move_up)
        self.buttons_layout.addWidget(self.up_button)

        self.down_button = QPushButton("Down")
        self.down_button.clicked.connect(self.move_down)
        self.buttons_layout.addWidget(self.down_button)

        self.clear_button = QPushButton("Clear List")
        self.clear_button.clicked.connect(self.list_widget.clear)
        self.buttons_layout.addWidget(self.clear_button)

        self.remove_button = QPushButton("Remove Item")
        self.remove_button.clicked.connect(self.remove_item)
        self.buttons_layout.addWidget(self.remove_button)

        self.show()

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
        item = QListWidgetItem(icon,  self.get_next_text())
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


class CheckboxList(QWidget):
    def __init__(self):
        super.__init__()
        self.layout = QVBoxLayout(self)
        self.checkboxes = []
        self.setLayout(self.layout)

    def add_checkbox(self, text):
        checkbox = QCheckBox(text)
        self.checkboxes.append(checkbox)
        self.layout.addWidget(checkbox)

    def get_checked(self):
        return [checkbox.text() for checkbox in self.checkboxes if checkbox.isChecked()]

    def get_unchecked(self):
        return [checkbox.text() for checkbox in self.checkboxes if not checkbox.isChecked()]



if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ImageListWindow()
    sys.exit(app.exec())

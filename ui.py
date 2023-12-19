import sys
import deepl
import sqlite3
from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget,
                             QPushButton, QWidget, QHBoxLayout,
                             QListWidgetItem, QVBoxLayout, QCheckBox,
                             QComboBox, QLabel, QScrollArea, QGroupBox,
                             QMessageBox, QSlider, QLineEdit, QDialog)
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent

import sracre
from api import Api

ICON_SIZE = 128
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')
DEEPL_QUOTA = 500000
ELEVENLABS_QUOTA = 20000

fps = 30
scale = 1.5
voice = "???"
video_length = 15
fade_duration = 0.25
audio_padding = 1000

db = sqlite3.connect("sracre.db")
cursor = db.cursor()

deepl_api = Api("deepl", db)
elevenlabs_api = Api("elevenlabs", db)

translator = deepl.Translator(deepl_api.get_key(0).key)
selected_languages = []
source_language = "???"


class MainList(QWidget):
    def __init__(self):
        super().__init__()
        self.text_list = []

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.setAcceptDrops(True)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.layout.addWidget(self.list_widget)

        self.buttons_layout = QHBoxLayout()
        self.layout.addLayout(self.buttons_layout)

        self.move_buttons_layout = QVBoxLayout()
        self.buttons_layout.addLayout(self.move_buttons_layout, 2)

        self.up_button = QPushButton("Move Up")
        self.up_button.clicked.connect(self.move_up)
        self.move_buttons_layout.addWidget(self.up_button)

        self.down_button = QPushButton("Move Down")
        self.down_button.clicked.connect(self.move_down)
        self.move_buttons_layout.addWidget(self.down_button)

        self.util_buttons_layout = QVBoxLayout()
        self.buttons_layout.addLayout(self.util_buttons_layout, 1)

        self.remove_button = QPushButton("Remove Item")
        self.remove_button.clicked.connect(self.remove_item)
        self.util_buttons_layout.addWidget(self.remove_button)

        self.clear_button = QPushButton("Clear List")
        self.clear_button.clicked.connect(self.clear_with_confirm)
        self.util_buttons_layout.addWidget(self.clear_button)

        self.done_button = QPushButton("Done")
        self.done_button.clicked.connect(self.done)
        self.layout.addWidget(self.done_button)

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

    def done(self):
        if self.list_widget.count() == 0:
            QMessageBox.warning(self, "Warning", "The list is empty")
            return
        if not selected_languages:
            QMessageBox.warning(self, "Warning", "No target languages selected")
            return
        if source_language == "???":
            QMessageBox.warning(self, "Warning", "No source language selected")
            return
        if voice == "???":
            QMessageBox.warning(self, "Warning", "No voice selected")
            return
        if QMessageBox.question(self, "Confirm", "Are you sure you want to start?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.Yes) != QMessageBox.StandardButton.Yes:
            return


class ApiKeysWindow(QDialog):
    class ApiLayout(QVBoxLayout):
        def __init__(self, name, api, max_quota):
            super().__init__()
            self.setAlignment(Qt.AlignmentFlag.AlignTop)

            self.api = api
            self.max_quota = max_quota

            self.label = QLabel(f"{name} API Keys:")
            self.addWidget(self.label)

            self.keys = api.get_all_keys()
            self.keys.sort(key=lambda x: x.quota_used / x.quota_total)
            self.keys.reverse()

            self.list = QListWidget()
            self.addWidget(self.list)
            for key in self.keys:
                self.list.addItem(f"{key.key} ({key.quota_used}/{key.quota_total})")

            self.add_layout = QHBoxLayout()
            self.add_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.addLayout(self.add_layout)

            self.add_edit = QLineEdit()
            self.add_edit.setPlaceholderText("API key")
            self.add_layout.addWidget(self.add_edit)

            self.add_button = QPushButton("+")
            self.add_button.clicked.connect(self.add_key)
            self.add_layout.addWidget(self.add_button)

        def add_key(self):
            key = self.add_edit.text().strip()
            if not key:
                return
            self.api.add_key(key, self.max_quota)
            self.list.addItem(f"{key} (0/{self.max_quota})")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("API Keys")
        self.resize(800, 300)

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.apis_layout = QHBoxLayout()
        self.layout.addLayout(self.apis_layout)

        self.deepl_layout = ApiKeysWindow.ApiLayout("DeepL", deepl_api, DEEPL_QUOTA)
        self.apis_layout.addLayout(self.deepl_layout)

        self.elevenlabs_layout = ApiKeysWindow.ApiLayout("ElevenLabs", elevenlabs_api, ELEVENLABS_QUOTA)
        self.apis_layout.addLayout(self.elevenlabs_layout)

        self.ok_button = QPushButton("Done")
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setDefault(True)
        self.layout.addWidget(self.ok_button)


class SettingsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.checkboxes = []
        self.setLayout(self.layout)

        self.combo_label = QLabel("Source language:")
        self.layout.addWidget(self.combo_label)

        self.source_langs = [lang.name for lang in translator.get_source_languages()]
        self.source_langs.sort()
        self.source_langs.insert(0, "???")

        self.source_combo = QComboBox()
        self.source_combo.currentTextChanged.connect(self.update_source)
        self.source_combo.addItems(self.source_langs)
        self.layout.addWidget(self.source_combo)

        self.target_label = QLabel("Target languages:")
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
            checkbox.stateChanged.connect(self.update_targets)
            self.checkboxes.append(checkbox)
            self.scrollable_layout.addWidget(checkbox)

        self.fps_label = QLabel("FPS:")
        self.layout.addWidget(self.fps_label)

        self.fps_combo = QComboBox()
        self.fps_combo.addItems(["30", "60"])
        self.fps_combo.currentTextChanged.connect(self.update_fps)
        self.layout.addWidget(self.fps_combo)

        self.voice_label = QLabel("Voice:")
        self.layout.addWidget(self.voice_label)

        self.voice_combo = QComboBox()
        self.voice_combo.addItems(sracre.get_voices())
        self.voice_combo.currentTextChanged.connect(self.update_voice)
        self.layout.addWidget(self.voice_combo)

        self.scale_label = QLabel(f"Scale ({scale}):")
        self.layout.addWidget(self.scale_label)

        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setMinimum(100)
        self.scale_slider.setMaximum(200)
        self.scale_slider.setTickInterval(10)
        self.scale_slider.setSingleStep(10)
        self.scale_slider.setValue(int(scale * 100))
        self.scale_slider.valueChanged.connect(self.update_scale)
        self.layout.addWidget(self.scale_slider)

        self.video_length_label = QLabel(f"Video length ({video_length}s):")
        self.layout.addWidget(self.video_length_label)

        self.video_length_slider = QSlider(Qt.Orientation.Horizontal)
        self.video_length_slider.setMinimum(5)
        self.video_length_slider.setMaximum(30)
        self.video_length_slider.setTickInterval(5)
        self.video_length_slider.setSingleStep(5)
        self.video_length_slider.setValue(video_length)
        self.video_length_slider.valueChanged.connect(self.update_video_length)
        self.layout.addWidget(self.video_length_slider)

        self.fade_duration_label = QLabel(f"Fade duration ({fade_duration}s):")
        self.layout.addWidget(self.fade_duration_label)

        self.fade_duration_slider = QSlider(Qt.Orientation.Horizontal)
        self.fade_duration_slider.setMinimum(0)
        self.fade_duration_slider.setMaximum(100)
        self.fade_duration_slider.setTickInterval(25)
        self.fade_duration_slider.setSingleStep(25)
        self.fade_duration_slider.setValue(int(fade_duration * 100))
        self.fade_duration_slider.valueChanged.connect(self.update_fade_duration)
        self.layout.addWidget(self.fade_duration_slider)

        self.audio_padding_label = QLabel(f"Audio padding ({audio_padding}ms):")
        self.layout.addWidget(self.audio_padding_label)

        self.audio_padding_slider = QSlider(Qt.Orientation.Horizontal)
        self.audio_padding_slider.setMinimum(0)
        self.audio_padding_slider.setMaximum(2000)
        self.audio_padding_slider.setTickInterval(250)
        self.audio_padding_slider.setSingleStep(250)
        self.audio_padding_slider.setValue(audio_padding)
        self.audio_padding_slider.valueChanged.connect(self.update_audio_padding)
        self.layout.addWidget(self.audio_padding_slider)

        self.api_keys_button = QPushButton("Edit API Keys")
        self.api_keys_button.clicked.connect(self.show_api_keys)
        self.layout.addWidget(self.api_keys_button)

    def update_targets(self):
        selected_languages.clear()
        for checkbox in self.checkboxes:
            if checkbox.isChecked():
                selected_languages.append(checkbox.text())

    def update_source(self):
        global source_language
        source_language = self.source_combo.currentText()

    def update_fps(self, value):
        global fps
        fps = value

    def update_scale(self, value):
        rounded_value = value // 10 * 10
        self.scale_slider.setValue(rounded_value)

        global scale
        scale = rounded_value / 100
        self.scale_label.setText(f"Scale ({scale}):")

    def update_voice(self, value):
        global voice
        voice = value

    def update_video_length(self, value):
        global video_length
        video_length = value
        self.video_length_label.setText(f"Video length ({video_length}):")

    def update_fade_duration(self, value):
        rounded_value = value // 25 * 25
        self.fade_duration_slider.setValue(rounded_value)

        global fade_duration
        fade_duration = rounded_value / 100
        self.fade_duration_label.setText(f"Fade duration ({fade_duration}):")

    def update_audio_padding(self, value):
        rounded_value = value // 250 * 250
        self.audio_padding_slider.setValue(rounded_value)

        global audio_padding
        audio_padding = rounded_value
        self.audio_padding_label.setText(f"Audio padding ({audio_padding}ms):")

    def show_api_keys(self):
        api_keys_window = ApiKeysWindow()
        api_keys_window.exec()


class SracreWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("sracre")
        self.resize(1200, 800)

        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout()
        self.main_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.main_widget)

        self.editor_layout = QHBoxLayout()
        self.main_layout.addLayout(self.editor_layout)

        self.list_group = QGroupBox("Content")
        self.list_group_layout = QVBoxLayout()
        self.list_group.setLayout(self.list_group_layout)
        self.editor_layout.addWidget(self.list_group, 2)

        self.list_widget = MainList()
        self.list_group_layout.addWidget(self.list_widget)

        self.language_group = QGroupBox("Settings")
        self.language_group_layout = QVBoxLayout()
        self.language_group.setLayout(self.language_group_layout)
        self.editor_layout.addWidget(self.language_group)

        self.languages_widget = SettingsWidget()
        self.language_group_layout.addWidget(self.languages_widget)

        self.show()

    def closeEvent(self, event):
        if QMessageBox.question(self, "Confirm Exit", "Are you sure you want to exit?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()


def setup_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS keys (api TEXT, key TEXT, quota_used INTEGER, quota_total INTEGER, "
                   "reset_time INTEGER)")
    db.commit()


if __name__ == '__main__':
    setup_db()
    sracre.set_api_key(elevenlabs_api.get_key(0).key)
    app = QApplication(sys.argv)
    ex = SracreWindow()
    sys.exit(app.exec())

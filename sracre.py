from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget,
                             QPushButton, QWidget, QHBoxLayout,
                             QListWidgetItem, QVBoxLayout, QCheckBox,
                             QComboBox, QLabel, QScrollArea, QGroupBox,
                             QMessageBox, QSlider, QLineEdit, QDialog,
                             QTextEdit, QFileDialog)
from PyQt6.QtCore import QSize, Qt, pyqtSignal, QPoint, QThread
from PyQt6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent, QMouseEvent, QTextCursor
import random
import sys
from typing import Optional
import deepl
import sqlite3
import os
import hashlib
import elevenlabs
import ffmpeg


class Keychain:
    class Error(Exception):
        pass

    class Entry:
        def __init__(self, api_name, key, quota_used, quota_total, reset_time):
            self.api_name = api_name
            self.key = key
            self.quota_used = quota_used
            self.quota_total = quota_total
            self.reset_time = reset_time

    def __init__(self, api_name):
        self.api_name = api_name

    def get_key(self, db_, quota_needed):
        try:
            return Keychain.Entry(
                *db_.cursor().execute("SELECT api, key, quota_used, quota_total, reset_time FROM keys "
                                      "WHERE api = ? AND quota_total - quota_used >= ? ORDER BY "
                                      "quota_used LIMIT 1", (self.api_name, quota_needed)).fetchone())
        except TypeError:
            raise Keychain.Error("No keys available")

    def add_key(self, db_, key, total_quota):
        db_.cursor().execute("INSERT INTO keys (api, key, quota_used, quota_total, reset_time) VALUES (?, ?, ?, ?, ?)",
                             (self.api_name, key, 0, total_quota, 0))
        db_.commit()

    def update_quota(self, db_, key, current, total, reset_time):
        print(f"Updating quota for {key} to {current}/{total} with reset time {reset_time}")
        db_.cursor().execute("UPDATE keys SET quota_used = ?, quota_total = ?, reset_time = ? WHERE api = ? AND key = ?"
                             , (current, total, reset_time, self.api_name, key))
        db_.commit()

    def get_all_keys(self, db_):
        try:
            return [Keychain.Entry(*row) for row in db_.cursor().execute("SELECT api, key, quota_used, quota_total, "
                                                                         "reset_time FROM keys WHERE api = ?",
                                                                         (self.api_name,)).fetchall()]
        except TypeError:
            raise Keychain.Error("No keys available")


ICON_SIZE = 128
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')
OUT_DIRS = ["output/audio", "output/videos", "output/clips", "output/done"]
DEEPL_QUOTA = 500000
ELEVENLABS_QUOTA = 20000

fps = 30
scale = 1.5
voice = "???"
video_length = 15
fade_duration = 0.25
audio_padding = 0.75

deepl_keychain = Keychain("deepl")
elevenlabs_keychain = Keychain("elevenlabs")

translator: Optional[deepl.Translator] = None
selected_languages = []
source_language = "???"
target_texts = {}

db = sqlite3.connect("sracre.db")


def get_settings():
    result = db.cursor().execute("SELECT key, value FROM settings").fetchall()
    return {key: value for key, value in result}


def set_setting(key, value):
    db.cursor().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()


def get_hash(items):
    hash_ = hashlib.sha256()
    for item in items:
        hash_.update(str(item).encode())
    return hash_.hexdigest()


def generate_audio(line):
    path = f"output/audio/{get_hash([line, voice])}.wav"
    if os.path.exists(path):
        print(f"Audio for \"{line}\" already exists. Remove it to regenerate.")
        return path

    print("Generating audio for:", line)
    db_ = sqlite3.connect("sracre.db")
    key = elevenlabs_keychain.get_key(db_, len(line))
    elevenlabs.set_api_key(key.key)

    audio = elevenlabs.generate(
        text=line,
        voice=voice,
        model="eleven_multilingual_v2",
    )
    with open(path, "wb") as f:
        f.write(audio)
    print("Saved audio to:", path)

    user_info = elevenlabs.User.from_api().subscription
    elevenlabs_keychain.update_quota(db_, key.key, user_info.character_count, user_info.character_limit,
                                     user_info.next_character_count_reset_unix)

    return path


PAN_DIRECTIONS = [-1, 1]
last_pan_directions = (random.choice(PAN_DIRECTIONS), random.choice(PAN_DIRECTIONS))


def get_next_pan_directions():
    global last_pan_directions
    pan_directions = last_pan_directions
    while pan_directions == last_pan_directions:
        pan_directions = (random.choice(PAN_DIRECTIONS), random.choice(PAN_DIRECTIONS))
    last_pan_directions = pan_directions
    return pan_directions


def generate_video(image):
    with open(image, "rb") as f:
        output_path = f"output/videos/{get_hash([f.read(), scale, video_length, fps])}.mp4"
    if os.path.exists(output_path):
        print(f"Video for \"{image}\" already exists. Remove it to regenerate.")
        return output_path

    total_frames = int(video_length * fps)
    zoom_increment = (scale - 1) / total_frames
    pan_directions = get_next_pan_directions()
    zoompan_filter = (
        f"scale=8000:-1,zoompan="
        f"z='min(zoom+{zoom_increment:.10f},{scale})'"
        f":x='(x+{pan_directions[0]})/a*on'"
        f":y='(y+{pan_directions[1]})*on'"
        f":d={total_frames}"
        f":s=1920x1080"
    )
    print(f"Generating clip from \"{image}\" with end scale {scale} and duration {video_length}")
    (
        ffmpeg.input(image, loop=1, framerate=fps)
        .output(output_path, vcodec='libx264', t=video_length, vf=zoompan_filter, pix_fmt='yuv420p')
        .run(quiet=True)
    )
    print("Saved clip to:", output_path)
    return output_path


def merge_audio_video(audio_path, video_path):
    audio_info = ffmpeg.probe(audio_path)
    video_info = ffmpeg.probe(video_path)
    audio_duration = float(audio_info['format']['duration'])
    video_duration = float(video_info['format']['duration'])
    total_duration = audio_duration + audio_padding
    if video_duration < total_duration:
        raise ValueError(f"Video is shorter than audio by {(total_duration - video_duration):.2f}s")

    audio_name = os.path.splitext(os.path.basename(audio_path))[0]
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    output_path = f"output/clips/{get_hash([audio_name, video_name])}.mp4"
    if os.path.exists(output_path):
        print(f"Clip for \"{audio_name}\" and \"{video_name}\" already exists. Remove it to regenerate.")
        return output_path

    print(f"Merging audio \"{audio_name}\" and video \"{video_name}\"")
    video_input = ffmpeg.input(video_path)
    video_input = video_input.trim(start=0, end=total_duration)

    audio_input = ffmpeg.input(audio_path)
    silent_audio = ffmpeg.input('anullsrc', f='lavfi', t=audio_padding)
    concat_audio = ffmpeg.concat(silent_audio, audio_input, silent_audio, v=0, a=1).filter('atrim', duration=total_duration)

    ffmpeg.output(video_input, concat_audio, output_path, vcodec='libx264', acodec='aac').run(quiet=True)
    print(f"Saved clip to \"{output_path}\"")
    return output_path


def concatenate_clips(clips):
    video_filters = []
    audio_filters = []
    clips_hash = get_hash([os.path.splitext(os.path.basename(clip))[0] for clip in clips])
    output_path = f"output/done/{clips_hash}.mp4"
    if os.path.exists(output_path):
        print(f"Concatenated clip for \"{output_path}\" already exists. Remove it to regenerate.")
        return output_path

    for clip in clips:
        clip_input = ffmpeg.input(clip)

        video = clip_input.video.filter('setpts', 'PTS-STARTPTS')
        video = video.filter('fade', type='in', start_time=0, duration=fade_duration)
        video = video.filter('fade', type='out', start_time=video_length - fade_duration, duration=fade_duration)
        video_filters.append(video)

        audio = clip_input.audio.filter('afade', type='in', start_time=0, duration=fade_duration)
        audio = audio.filter('afade', type='out', start_time=video_length - fade_duration, duration=fade_duration)
        audio_filters.append(audio)

    print("Concatenating clips...")
    concatenated_video = ffmpeg.concat(*video_filters, v=1, a=0)
    concatenated_audio = ffmpeg.concat(*audio_filters, v=0, a=1)
    ffmpeg.output(concatenated_video, concatenated_audio, output_path).run(quiet=True)
    print("Saved concatenated clip to:", output_path)


def create_clip(line, image):
    video_file = generate_video(image)
    audio_file = generate_audio(line)
    return merge_audio_video(audio_file, video_file)


def get_voices():
    voices = elevenlabs.voices()
    return sorted([v.name for v in voices])


class TranslationThread(QThread):
    translation_done = pyqtSignal(str)
    has_error = pyqtSignal(Exception)

    def __init__(self, text, targets):
        super().__init__()
        self.text = text
        self.targets = targets
        self.error = None

    def run(self):
        try:
            db_ = sqlite3.connect("sracre.db")

            text_len = sum([len(line) for line in self.text]) * len(self.targets)
            key = deepl_keychain.get_key(db_, text_len)
            translator_ = deepl.Translator(key.key)

            target_langs = {lang.name: lang for lang in translator_.get_target_languages()}
            source_lang = {lang.name: lang for lang in translator_.get_source_languages()}[source_language]

            global target_texts
            for target in self.targets:
                print(f"Translating to \"{target}\" from \"{source_language}\"")
                translation = translator_.translate_text(self.text, source_lang=source_lang,
                                                         target_lang=target_langs[target])
                target_texts[target] = [line.text for line in translation]
                self.translation_done.emit(target)

            usage = translator_.get_usage()
            quota_curr = int(usage.character.count)
            quota_total = int(usage.character.limit)
            print(f"{quota_curr} == {key.quota_used+text_len}")
            deepl_keychain.update_quota(db_, key.key, quota_curr, quota_total, 0)
        except Exception as e:
            self.has_error.emit(e)


class TranslationWindow(QDialog):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.setWindowTitle("Translation")
        self.resize(800, 600)

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.texts_layout = QHBoxLayout()
        self.layout.addLayout(self.texts_layout)

        self.source_layout = QVBoxLayout()
        self.texts_layout.addLayout(self.source_layout)

        self.source_combo = QComboBox()
        self.source_combo.addItem(source_language)
        self.source_combo.setDisabled(True)
        self.source_layout.addWidget(self.source_combo)

        self.source_text_edit = QTextEdit()
        self.source_text_edit.setReadOnly(True)
        self.source_text_edit.setText("\n\n".join(text))
        self.source_layout.addWidget(self.source_text_edit)

        self.target_layout = QVBoxLayout()
        self.texts_layout.addLayout(self.target_layout)

        self.target_combo = QComboBox()
        self.target_combo.addItems(selected_languages)
        self.target_combo.currentTextChanged.connect(self.change_viewed_target)
        self.target_layout.addWidget(self.target_combo)

        self.target_text_edit = QTextEdit()
        self.target_text_edit.setReadOnly(True)
        self.target_layout.addWidget(self.target_text_edit)

        self.buttons_layout = QHBoxLayout()
        self.layout.addLayout(self.buttons_layout)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setDefault(True)
        self.buttons_layout.addWidget(self.cancel_button)

        self.ok_button = QPushButton("OK")
        self.ok_button.clicked.connect(self.accept)
        self.buttons_layout.addWidget(self.ok_button)

        if len(target_texts) == 0 and len(selected_languages) > 0:
            self.worker = TranslationThread(self.text, selected_languages)
            self.worker.translation_done.connect(self.on_translation_done)
            self.worker.has_error.connect(self.on_translation_error)
            self.worker.start()
        else:
            print("Translation already done")

    def change_viewed_target(self):
        target = self.target_combo.currentText()
        self.target_text_edit.setText("\n\n".join(target_texts[target]) if target in target_texts else "???")

    def on_translation_done(self, target):
        if self.target_combo.currentText() != target:
            return
        self.change_viewed_target()

    def on_translation_error(self, error):
        QMessageBox.critical(self, "Error", str(error))


class WorkerThread(QThread):
    has_error = pyqtSignal(Exception)

    def __init__(self, items):
        super().__init__()
        self.items = items

    def run(self):
        try:
            texts = target_texts
            texts[source_language] = [text for (_, text) in self.items]
            images = [image for (image, _) in self.items]

            for (lang, text) in texts.items():
                print(f"\n----\nCreating clips for \"{lang}\"")
                clips = []
                for (line, image) in zip(text, images):
                    clips.append(create_clip(line, image))
                concatenate_clips(clips)
            print("\n----\nDone!")
        except Exception as e:
            self.has_error.emit(e)


class ListWidget(QListWidget):
    imageDoubleClicked = pyqtSignal(QListWidgetItem)
    textDoubleClicked = pyqtSignal(QListWidgetItem)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        item = self.itemAt(event.pos())
        if not item:
            return

        if self.is_image_click(event.pos(), item):
            self.imageDoubleClicked.emit(item)
            return

        self.textDoubleClicked.emit(item)
        super().mouseDoubleClickEvent(event)

    def is_image_click(self, click_position: QPoint, item: QListWidgetItem):
        icon_area = self.visualItemRect(item)
        icon_area.setWidth(self.iconSize().width())  # Assume icon is at the left
        return icon_area.contains(click_position)


class EditorWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.worker = None
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)
        self.setAcceptDrops(True)

        self.text_list = []
        self.items = []

        self.list_widget = ListWidget()
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.list_widget.imageDoubleClicked.connect(self.on_image_double_clicked)
        self.list_widget.itemChanged.connect(self.on_item_changed)
        self.layout.addWidget(self.list_widget)

        self.buttons_layout = QHBoxLayout()
        self.buttons_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.layout.addLayout(self.buttons_layout)

        self.up_button = QPushButton("Move Up")
        self.up_button.clicked.connect(self.move_up)
        self.buttons_layout.addWidget(self.up_button)

        self.down_button = QPushButton("Move Down")
        self.down_button.clicked.connect(self.move_down)
        self.buttons_layout.addWidget(self.down_button)

        self.remove_button = QPushButton("Remove Item")
        self.remove_button.clicked.connect(self.remove_item)
        self.buttons_layout.addWidget(self.remove_button)

        self.clear_button = QPushButton("Clear List")
        self.clear_button.clicked.connect(self.clear_with_confirm)
        self.buttons_layout.addWidget(self.clear_button)

        self.done_button = QPushButton("Done")
        self.done_button.clicked.connect(self.done)
        self.done_button.setDefault(True)
        self.buttons_layout.addWidget(self.done_button, 1)

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
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list_widget.addItem(item)
        self.items.append((path, item.text()))

    def on_image_double_clicked(self, item):
        row = self.list_widget.row(item)
        ext_filter = f"Images ({' '.join(['*' + ext for ext in IMAGE_EXT])})"
        new_image_path, _ = QFileDialog.getOpenFileName(self, "Select Image", "", ext_filter)
        if new_image_path:
            self.items[row] = (new_image_path, self.items[row][1])
            self.list_widget.item(row).setIcon(QIcon(QPixmap(new_image_path)))

    def get_next_text(self):
        return self.text_list.pop() if self.text_list else "???"

    def load_text(self, path):
        self.text_list.clear()
        with open(path, 'r') as file:
            self.text_list.extend(line.strip() for line in file if line.strip())
            self.text_list.reverse()
            self.update_text()

    def update_text(self):
        filled_up_to = min(self.list_widget.count(), len(self.text_list))
        for i in range(self.list_widget.count()):
            self.items[i] = (self.items[i][0], self.get_next_text() if i < filled_up_to else "???")
            self.list_widget.item(i).setText(self.items[i][1])

    def on_item_changed(self, item):
        row = self.list_widget.row(item)
        self.items[row] = (self.items[row][0], item.text())

    def remove_item(self):
        if self.list_widget.count() == 0:
            return
        if QMessageBox.question(self, "Confirm Remove", "Are you sure you want to remove the selected item?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            row = self.list_widget.currentRow()
            self.list_widget.takeItem(row)
            self.items.pop(row)

    def move_up(self):
        current = self.list_widget.currentRow()
        if current > 0:
            self.list_widget.insertItem(current - 1, self.list_widget.takeItem(current))
            self.list_widget.setCurrentRow(current - 1)
            self.items[current], self.items[current - 1] = self.items[current - 1], self.items[current]

    def move_down(self):
        current = self.list_widget.currentRow()
        if current < self.list_widget.count() - 1:
            self.list_widget.insertItem(current + 1, self.list_widget.takeItem(current))
            self.list_widget.setCurrentRow(current + 1)
            self.items[current], self.items[current + 1] = self.items[current + 1], self.items[current]

    def clear_with_confirm(self):
        if self.list_widget.count() < 0:
            return
        if QMessageBox.question(self, "Confirm Clear", "Are you sure you want to clear the list?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.list_widget.clear()
            self.items.clear()

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

        for (image, text) in self.items:
            if text == "???":
                QMessageBox.warning(self, "Warning", "Not all items have text")
                return

        ex = TranslationWindow([text for (_, text) in self.items])
        if ex.exec() != QDialog.DialogCode.Accepted:
            return

        print("Starting...")
        self.worker = WorkerThread(self.items)
        self.worker.has_error.connect(self.show_error_dialog)
        self.worker.start()

    def show_error_dialog(self, error):
        QMessageBox.critical(self, "Error", str(error))


class ApiKeysWindow(QDialog):
    class ApiLayout(QVBoxLayout):
        def __init__(self, name, api, max_quota):
            super().__init__()
            self.setAlignment(Qt.AlignmentFlag.AlignTop)

            self.api = api
            self.max_quota = max_quota

            self.label = QLabel(f"{name} API Keys:")
            self.addWidget(self.label)

            self.keys = api.get_all_keys(db)

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
            self.api.add_key(db, key, self.max_quota)
            self.list.addItem(f"{key} (0/{self.max_quota})")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("API Keys")
        self.resize(800, 300)

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.apis_layout = QHBoxLayout()
        self.layout.addLayout(self.apis_layout)

        self.deepl_layout = ApiKeysWindow.ApiLayout("DeepL", deepl_keychain, DEEPL_QUOTA)
        self.apis_layout.addLayout(self.deepl_layout)

        self.elevenlabs_layout = ApiKeysWindow.ApiLayout("ElevenLabs", elevenlabs_keychain, ELEVENLABS_QUOTA)
        self.apis_layout.addLayout(self.elevenlabs_layout)

        self.ok_button = QPushButton("Done")
        self.ok_button.clicked.connect(self.accept)
        self.ok_button.setDefault(True)
        self.layout.addWidget(self.ok_button)


class SettingsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(5)
        self.checkboxes = []
        self.setLayout(self.layout)

        self.combo_label = QLabel("Source language:")
        self.layout.addWidget(self.combo_label)

        self.source_langs = [lang.name for lang in translator.get_source_languages()]
        self.source_langs.sort()

        self.source_combo = QComboBox()
        self.source_combo.addItems(self.source_langs)
        if source_language in self.source_langs:
            self.source_combo.setCurrentText(source_language)
        else:
            self.source_combo.addItem("???")
            self.source_combo.setCurrentText("???")
        self.source_combo.currentTextChanged.connect(self.update_source)
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
            if selected_languages:
                checkbox.setChecked(lang in selected_languages)
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

        voices = get_voices()
        self.voice_combo = QComboBox()
        self.voice_combo.addItems(voices)
        if voice in voices:
            self.voice_combo.setCurrentText(voice)
        self.voice_combo.currentTextChanged.connect(self.update_voice)
        self.layout.addWidget(self.voice_combo)

        self.scale_label = QLabel(f"Final scale ({scale}):")
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

        self.audio_padding_label = QLabel(f"Audio padding ({audio_padding}s):")
        self.layout.addWidget(self.audio_padding_label)

        self.audio_padding_slider = QSlider(Qt.Orientation.Horizontal)
        self.audio_padding_slider.setMinimum(0)
        self.audio_padding_slider.setMaximum(200)
        self.audio_padding_slider.setTickInterval(25)
        self.audio_padding_slider.setSingleStep(25)
        self.audio_padding_slider.setValue(int(audio_padding * 100))
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
        set_setting("selected_languages", ",".join(selected_languages))

    def update_source(self):
        global source_language
        source_language = self.source_combo.currentText()
        set_setting("source_language", source_language)
        if source_language != "???":
            self.source_combo.removeItem(self.source_combo.findText("???"))

    def update_fps(self, value):
        global fps
        fps = value
        set_setting("fps", fps)

    def update_scale(self, value):
        rounded_value = value // 10 * 10
        self.scale_slider.setValue(rounded_value)

        global scale
        scale = rounded_value / 100
        self.scale_label.setText(f"Final scale ({scale}):")
        set_setting("scale", scale)

    def update_voice(self, value):
        global voice
        voice = value
        set_setting("voice", voice)

    def update_video_length(self, value):
        global video_length
        video_length = value
        self.video_length_label.setText(f"Video length ({video_length}):")
        set_setting("video_length", video_length)

    def update_fade_duration(self, value):
        rounded_value = value // 25 * 25
        self.fade_duration_slider.setValue(rounded_value)

        global fade_duration
        fade_duration = rounded_value / 100
        self.fade_duration_label.setText(f"Fade duration ({fade_duration}):")
        set_setting("fade_duration", fade_duration)

    def update_audio_padding(self, value):
        rounded_value = value // 25 * 25
        self.audio_padding_slider.setValue(rounded_value)

        global audio_padding
        audio_padding = rounded_value / 100
        self.audio_padding_label.setText(f"Audio padding ({audio_padding}ms):")
        set_setting("audio_padding", audio_padding)

    def show_api_keys(self):
        api_keys_window = ApiKeysWindow()
        api_keys_window.exec()


class StreamRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, text):
        self.text_widget.insertPlainText(text)
        self.text_widget.moveCursor(QTextCursor.MoveOperation.End)

    def flush(self):
        pass


class SracreWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("sracre")
        self.resize(1200, 800)

        self.main_widget = QWidget()
        self.layout = QVBoxLayout()
        self.main_widget.setLayout(self.layout)
        self.setCentralWidget(self.main_widget)

        self.editor_layout = QHBoxLayout()
        self.layout.addLayout(self.editor_layout, 3)

        self.editor_group = QGroupBox("Editor")
        self.editor_group_layout = QVBoxLayout()
        self.editor_group.setLayout(self.editor_group_layout)
        self.editor_layout.addWidget(self.editor_group, 2)

        self.list_widget = EditorWidget()
        self.editor_group_layout.addWidget(self.list_widget)

        self.language_group = QGroupBox("Settings")
        self.language_group_layout = QVBoxLayout()
        self.language_group.setLayout(self.language_group_layout)
        self.editor_layout.addWidget(self.language_group)

        self.languages_widget = SettingsWidget()
        self.language_group_layout.addWidget(self.languages_widget)

        self.output_group = QGroupBox("Output")
        self.output_group_layout = QVBoxLayout()
        self.output_group.setLayout(self.output_group_layout)
        self.layout.addWidget(self.output_group, 1)

        self.output_textedit = QTextEdit()
        self.output_textedit.setReadOnly(True)
        self.output_group_layout.addWidget(self.output_textedit)

        out_redirector = StreamRedirector(self.output_textedit)
        sys.stdout = out_redirector
        sys.stderr = out_redirector

        print("Welcome to sracre! Waiting for work...")
        self.show()

    def closeEvent(self, event):
        if QMessageBox.question(self, "Confirm Exit", "Are you sure you want to exit?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()


class SracreApp(QApplication):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for directory in OUT_DIRS:
            os.makedirs(directory, exist_ok=True)

        cursor = db.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS keys (api TEXT, key TEXT, quota_used INTEGER, "
                       "quota_total INTEGER, reset_time INTEGER)")
        db.commit()
        global translator
        translator = deepl.Translator(deepl_keychain.get_key(db, 0).key)
        elevenlabs.set_api_key(elevenlabs_keychain.get_key(db, 0).key)
        settings = get_settings()

        global source_language, selected_languages, fps, scale, voice, video_length, fade_duration, audio_padding
        if "source_language" in settings:
            source_language = settings["source_language"]
        if "selected_languages" in settings:
            selected_languages = settings["selected_languages"].split(",")
        if "fps" in settings:
            fps = settings["fps"]
        if "scale" in settings:
            scale = float(settings["scale"])
        if "voice" in settings:
            voice = settings["voice"]
        if "video_length" in settings:
            video_length = int(settings["video_length"])
        if "fade_duration" in settings:
            fade_duration = float(settings["fade_duration"])
        if "audio_padding" in settings:
            audio_padding = float(settings["audio_padding"])

        self.window = SracreWindow()
        self.window.show()


if __name__ == '__main__':
    sys.exit(SracreApp(sys.argv).exec())

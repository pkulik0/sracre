import sys
import deepl
import sqlite3
import os
import hashlib
import elevenlabs
import ffmpeg
from PyQt6.QtWidgets import (QApplication, QMainWindow, QListWidget,
                             QPushButton, QWidget, QHBoxLayout,
                             QListWidgetItem, QVBoxLayout, QCheckBox,
                             QComboBox, QLabel, QScrollArea, QGroupBox,
                             QMessageBox, QSlider, QLineEdit, QDialog, QTextEdit)
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDropEvent


class Api:
    class Entry:
        def __init__(self, api_name, key, quota_used, quota_total, reset_time):
            self.api_name = api_name
            self.key = key
            self.quota_used = quota_used
            self.quota_total = quota_total
            self.reset_time = reset_time

    def __init__(self, api_name, db):
        self.db = db
        self.cursor = db.cursor()
        self.api_name = api_name

    def get_key(self, quota_needed):
        return Api.Entry(*self.cursor.execute("SELECT api, key, quota_used, quota_total, reset_time FROM keys "
                                              "WHERE api = ? AND quota_total - quota_used >= ? ORDER BY "
                                              "quota_used LIMIT 1", (self.api_name, quota_needed)).fetchone())

    def add_key(self, key, quota):
        self.cursor.execute("INSERT INTO keys (api, key, quota_used, quota_total, reset_time) VALUES (?, ?, ?, ?, ?)",
                            (self.api_name, key, 0, quota, 0))
        self.db.commit()

    def incr_key_quota(self, key, quota):
        self.cursor.execute("UPDATE keys SET quota_used = quota_used + ? WHERE key = ?", (quota, key))
        self.db.commit()

    def get_all_keys(self):
        return [Api.Entry(*row) for row in self.cursor.execute("SELECT api, key, quota_used, quota_total, "
                                                               "reset_time FROM keys WHERE api = ?",
                                                               (self.api_name,)).fetchall()]


ICON_SIZE = 128
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp')
OUT_DIRS = ["output/audio", "output/videos", "output/clips"]
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


def get_settings():
    result = cursor.execute("SELECT key, value FROM settings").fetchall()
    return {key: value for key, value in result}


def set_setting(key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()


def generate_audio(line, voice):
    line_hash = hashlib.sha256(line.encode()).hexdigest()
    path = f"output/audio/{line_hash}.wav"
    if os.path.exists(path):
        print(f"Audio for \"{line}\" already exists. Remove it to regenerate.")
        return path

    print("Generating audio for:", line)
    audio = elevenlabs.generate(
        text=line,
        voice=voice,
        model="eleven_multilingual_v2",
    )
    with open(path, "wb") as f:
        f.write(audio)
    print("Saved audio to:", path)
    return path


def generate_video(image):
    with open(image, "rb") as f:
        image_hash = hashlib.sha256(f.read()).hexdigest()

    output = f"output/videos/{image_hash}.mp4"
    if os.path.exists(output):
        print(f"Video for \"{image}\" already exists. Remove it to regenerate.")
        return output

    total_frames = int(video_length * fps)
    zoom_increment = (scale - 1) / total_frames
    zoompan_filter = (
        f"scale=8000:-1,zoompan=z='min(zoom+{zoom_increment:.10f},{scale})':"
        f"d={total_frames}:x='if(gte(zoom,1.5),x,x+1/a)':y='if(gte(zoom,1.5),y,y+1)':s=1920x1080"
    )
    print(f"Generating clip from \"{image}\" with end scale {scale} and duration {video_length}")
    (
        ffmpeg.input(image, loop=1, framerate=fps)
        .output(output, vcodec='libx264', t=video_length, vf=zoompan_filter, pix_fmt='yuv420p')
        .run(quiet=True)
    )
    print("Saved clip to:", output)
    return output


def merge_audio_video(audio_path, video_path):
    audio_info = ffmpeg.probe(audio_path)
    video_info = ffmpeg.probe(video_path)
    audio_duration = float(audio_info['format']['duration'])
    video_duration = float(video_info['format']['duration'])
    if video_duration < audio_duration:
        raise ValueError("Video is shorter than audio")

    audio_name = os.path.splitext(os.path.basename(audio_path))[0]
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    output = f"output/clips/{audio_name}_{video_name}.mp4"
    if os.path.exists(output):
        print(f"Clip for \"{audio_name}\" and \"{video_name}\" already exists. Remove it to regenerate.")
        return output

    print(f"Merging audio \"{audio_name}\" and video \"{video_name}\"")
    video_input = ffmpeg.input(video_path)
    audio_input = ffmpeg.input(audio_path)
    ffmpeg.output(video_input, audio_input, output,
                  map='0:v,1:a',
                  vcodec='copy', acodec='aac',
                  strict='experimental',
                  shortest=None,
                  af=f'adelay={audio_padding}|{audio_padding},apad=pad_dur={audio_padding/1000}').run(quiet=True)
    print(f"Saved clip to \"{output}\"")
    return output


def concatenate_clips(clips):
    video_filters = []
    audio_filters = []
    clips_hash = hashlib.sha256()
    for clip in clips:
        clip_name = os.path.splitext(os.path.basename(clip))[0]
        clips_hash.update(clip_name.encode())

        clip_input = ffmpeg.input(clip)

        video = clip_input.video.filter('setpts', 'PTS-STARTPTS')
        video = video.filter('fade', type='in', start_time=0, duration=fade_duration)
        video = video.filter('fade', type='out', start_time=video_length - fade_duration, duration=fade_duration)
        video_filters.append(video)

        audio = clip_input.audio.filter('afade', type='in', start_time=0, duration=fade_duration)
        audio = audio.filter('afade', type='out', start_time=video_length - fade_duration, duration=fade_duration)
        audio_filters.append(audio)

    output = f"output/{clips_hash.hexdigest()}.mp4"
    if os.path.exists(output):
        print(f"Concatenated clip for \"{clips_hash.hexdigest()}\" already exists. Remove it to regenerate.")
        return output

    print("Concatenating clips...")
    concatenated_video = ffmpeg.concat(*video_filters, v=1, a=0)
    concatenated_audio = ffmpeg.concat(*audio_filters, v=0, a=1)
    ffmpeg.output(concatenated_video, concatenated_audio, output).run(quiet=True)
    print("Saved concatenated clip to:", output)


def create_clip(line, image):
    video_file = generate_video(image)
    audio_file = generate_audio(line, voice)
    return merge_audio_video(audio_file, video_file)


def get_voices():
    voices = elevenlabs.voices()
    return sorted([v.name for v in voices])


def do_work(lines, images):
    clips = []
    for i, (line, image) in enumerate(zip(lines, images)):
        clips.append(create_clip(line, image))
    concatenate_clips(clips)


class MainList(QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)
        self.setAcceptDrops(True)

        self.text_list = []

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list_widget.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
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
        if self.list_widget.count() == 0:
            return
        if QMessageBox.question(self, "Confirm Remove", "Are you sure you want to remove the selected item?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self.list_widget.takeItem(self.list_widget.currentRow())

    def move_up(self):
        current = self.list_widget.currentRow()
        if current > 0:
            self.list_widget.insertItem(current - 1, self.list_widget.takeItem(current))
            self.list_widget.setCurrentRow(current - 1)

    def move_down(self):
        current = self.list_widget.currentRow()
        if current < self.list_widget.count() - 1:
            self.list_widget.insertItem(current + 1, self.list_widget.takeItem(current))
            self.list_widget.setCurrentRow(current + 1)

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
        self.layout.setSpacing(5)
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

        if source_language in self.source_langs:
            self.source_combo.setCurrentText(source_language)

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

        self.voice_combo = QComboBox()
        self.voice_combo.addItems(get_voices())
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
        set_setting("selected_languages", ",".join(selected_languages))

    def update_source(self):
        global source_language
        source_language = self.source_combo.currentText()
        set_setting("source_language", source_language)

    def update_fps(self, value):
        global fps
        fps = value
        set_setting("fps", fps)

    def update_scale(self, value):
        rounded_value = value // 10 * 10
        self.scale_slider.setValue(rounded_value)

        global scale
        scale = rounded_value / 100
        self.scale_label.setText(f"Scale ({scale}):")
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
        rounded_value = value // 250 * 250
        self.audio_padding_slider.setValue(rounded_value)

        global audio_padding
        audio_padding = rounded_value
        self.audio_padding_label.setText(f"Audio padding ({audio_padding}ms):")
        set_setting("audio_padding", audio_padding)

    def show_api_keys(self):
        api_keys_window = ApiKeysWindow()
        api_keys_window.exec()


class StreamRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, text):
        self.text_widget.append(text)

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

        self.list_widget = MainList()
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
        sys.stdout = StreamRedirector(self.output_textedit)

        print("Welcome to sracre! Waiting for work...")

        self.show()

    def closeEvent(self, event):
        if QMessageBox.question(self, "Confirm Exit", "Are you sure you want to exit?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()


def setup_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS keys (api TEXT, key TEXT, quota_used INTEGER, quota_total INTEGER, "
                   "reset_time INTEGER)")
    db.commit()


class SracreApp(QApplication):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for directory in OUT_DIRS:
            os.makedirs(directory, exist_ok=True)

        setup_db()
        elevenlabs.set_api_key(elevenlabs_api.get_key(0).key)

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
            audio_padding = int(settings["audio_padding"])

        self.window = SracreWindow()
        self.window.show()


if __name__ == '__main__':
    sys.exit(SracreApp(sys.argv).exec())

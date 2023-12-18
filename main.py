import argparse
import os

import numpy as np
from PIL import Image
from elevenlabs import generate, set_api_key

from moviepy.editor import AudioFileClip, ImageSequenceClip

ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "webp"]
DIRS = ["output", "output/audio", "output/frames", "output/clips"]


def parse_args():
    parser = argparse.ArgumentParser(description="sracre")
    parser.add_argument("--text", type=str, default="text.txt", help="File with voice-over text")
    parser.add_argument("--images", type=str, default="images", help="Images directory")
    parser.add_argument("--fps", type=int, default=30, help="FPS")
    parser.add_argument("--scale", type=float, default=1.1, help="Peak scale of images")
    parser.add_argument("--voice", type=str, default="Adam", help="Voice")
    parser.add_argument("--speed", type=float, default=1.0, help="Speed of the voice")
    parser.add_argument("--api-key", type=str, default=None, help="Elevenlabs API key", required=True)
    return parser.parse_args()


def load_data(text_file, images_dir):
    lines = []
    with open(text_file, "r") as f:
        lines_raw = f.readlines()
        for line in lines_raw:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)

    images = []
    for i in range(len(lines)):
        was_found = False
        for ext in ALLOWED_EXTENSIONS:
            filename = os.path.join(images_dir, f"{i}.{ext}")
            if os.path.exists(filename):
                was_found = True
                images.append(Image.open(filename))
                break
        if not was_found:
            raise FileNotFoundError(f"Image {i} was not found")
    return lines, images


def generate_audio(lines, voice):
    audio_files = []
    for i, line in enumerate(lines):
        print("Generating output for line:", line)
        audio = generate(
            text=line,
            voice=voice,
            model="eleven_multilingual_v2",
        )
        path = f"output/audio/{i}.wav"
        with open(path, "wb") as f:
            f.write(audio)
            print("Saved audio to:", f.name)
            audio_files.append(AudioFileClip(path))
    return audio_files


def generate_frames(image, scale, fps, duration):
    frames = []
    total_frames = int(fps * duration)
    for i, ratio in enumerate(np.linspace(1.0, scale, total_frames)):
        old_size = image.size
        new_size = tuple(int(x * ratio) for x in image.size)
        resized = image.resize(new_size)

        left = (new_size[0] - old_size[0]) // 2
        top = (new_size[1] - old_size[1]) // 2
        right = left + old_size[0]
        bottom = top + old_size[1]
        cropped = resized.crop((left, top, right, bottom))

        path = f"output/frames/{i}.png"
        cropped.save(path)
        frames.append(path)
    return frames


def main():
    for directory in DIRS:
        os.makedirs(directory, exist_ok=True)

    args = parse_args()
    print("Running with args:\n", args)

    set_api_key(args.api_key)

    lines, images = load_data(args.text, args.images)

    audio_files = generate_audio(lines, args.voice)
    for i, (audio, image) in enumerate(zip(audio_files, images)):
        frame_files = generate_frames(image, args.scale, args.fps, audio.duration)
        print("Generated", len(frame_files), "frames")

        clip = ImageSequenceClip(frame_files, fps=args.fps).set_audio(audio)
        clip_path = "output/clips/{}.mp4".format(i)
        clip.write_videofile(clip_path, fps=args.fps)
        print("Saved subclip to:", clip_path)


if __name__ == "__main__":
    main()

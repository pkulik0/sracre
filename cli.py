import argparse
import os
import hashlib

import ffmpeg
from elevenlabs import generate, set_api_key

ALLOWED_EXTENSIONS = ["png", "jpg", "jpeg", "webp"]
DIRS = ["output/audio", "output/videos", "output/clips"]
VIDEO_LENGTH = 15
FADE_DURATION = 0.25
AUDIO_PADDING = 1000


def parse_args():
    parser = argparse.ArgumentParser(description="sracre")
    parser.add_argument("--text", type=str, default="text.txt", help="File with voice-over text")
    parser.add_argument("--images", type=str, default="images", help="Images directory")
    parser.add_argument("--fps", type=int, default=30, help="FPS")
    parser.add_argument("--scale", type=float, default=1.5, help="Peak scale of images")
    parser.add_argument("--voice", type=str, default="Adam", help="Voice")
    parser.add_argument("--speed", type=float, default=0.8, help="Speed of the voice")
    parser.add_argument("--api-key", type=str, default=None, help="Elevenlabs API key", required=True)
    args = parser.parse_args()

    print("Settings: ")
    print("\timages:", args.images)
    print("\tfps:", args.fps)
    print("\tscale:", args.scale)
    print("\tvoice:", args.voice)
    print("\ttext:", args.text)
    print("\tspeed:", args.speed)
    print("\tapi-key:", args.api_key)
    return args


def load_data(text_file, images_dir):
    print(f"Loading text from \"{text_file}\"")
    lines = []
    with open(text_file, "r") as f:
        lines_raw = f.readlines()
        for line in lines_raw:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)

    print(f"Loading images from \"{images_dir}\"")
    images = []
    for i in range(len(lines)):
        was_found = False
        for ext in ALLOWED_EXTENSIONS:
            filename = os.path.join(images_dir, f"{i}.{ext}")
            if os.path.exists(filename):
                was_found = True
                images.append(filename)
                break
        if not was_found:
            raise FileNotFoundError(f"Image {i} was not found")
    return lines, images


def generate_audio(line, voice):
    line_hash = hashlib.sha256(line.encode()).hexdigest()
    path = f"output/audio/{line_hash}.wav"
    if os.path.exists(path):
        print(f"Audio for \"{line}\" already exists. Remove it to regenerate.")
        return path

    print("Generating audio for:", line)
    audio = generate(
        text=line,
        voice=voice,
        model="eleven_multilingual_v2",
    )
    with open(path, "wb") as f:
        f.write(audio)
    print("Saved audio to:", path)
    return path


def generate_video(image, scale, fps):
    with open(image, "rb") as f:
        image_hash = hashlib.sha256(f.read()).hexdigest()

    output = f"output/videos/{image_hash}.mp4"
    if os.path.exists(output):
        print(f"Video for \"{image}\" already exists. Remove it to regenerate.")
        return output

    total_frames = int(VIDEO_LENGTH * fps)
    zoom_increment = (scale - 1) / total_frames
    zoompan_filter = (
        f"scale=8000:-1,zoompan=z='min(zoom+{zoom_increment:.10f},{scale})':"
        f"d={total_frames}:x='if(gte(zoom,1.5),x,x+1/a)':y='if(gte(zoom,1.5),y,y+1)':s=1920x1080"
    )
    print(f"Generating clip from \"{image}\" with end scale {scale} and duration {VIDEO_LENGTH}")
    (
        ffmpeg.input(image, loop=1, framerate=fps)
        .output(output, vcodec='libx264', t=VIDEO_LENGTH, vf=zoompan_filter, pix_fmt='yuv420p')
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
                  af=f'adelay={AUDIO_PADDING}|{AUDIO_PADDING},apad=pad_dur={AUDIO_PADDING/1000}').run(quiet=True)
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
        video = video.filter('fade', type='in', start_time=0, duration=FADE_DURATION)
        video = video.filter('fade', type='out', start_time=VIDEO_LENGTH - FADE_DURATION, duration=FADE_DURATION)
        video_filters.append(video)

        audio = clip_input.audio.filter('afade', type='in', start_time=0, duration=FADE_DURATION)
        audio = audio.filter('afade', type='out', start_time=VIDEO_LENGTH - FADE_DURATION, duration=FADE_DURATION)
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


def main():
    for directory in DIRS:
        os.makedirs(directory, exist_ok=True)
    args = parse_args()
    set_api_key(args.api_key)

    lines, images = load_data(args.text, args.images)
    clips = []
    for i, (line, image) in enumerate(zip(lines, images)):
        video_file = generate_video(image, args.scale, args.fps)
        audio_file = generate_audio(line, args.voice)
        clips.append(merge_audio_video(audio_file, video_file))

    concatenate_clips(clips)


if __name__ == "__main__":
    main()

import os
import re
import json
import math
import shutil
import string
import textwrap
import tempfile
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import streamlit as st
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

import whisper

APP_TITLE = "AI Lyric Video Generator"
VIDEO_W = 1280
VIDEO_H = 720
FPS = 30

STOPWORDS = {
    "the","and","for","with","that","this","from","you","your","are","was","were","will","they","them",
    "she","his","her","our","but","not","all","out","about","into","over","under","then","than","when",
    "what","where","who","why","how","have","has","had","been","being","too","very","can","could","should",
    "would","there","their","just","like","more","some","any","one","two","three","four","five","six","seven",
    "eight","nine","ten","i","me","my","we","us","he","him","it","its","a","an","to","of","in","on","at","as","is",
    "am","or","if","so","do","does","did","no","yes","up","down","left","right","off","on","be","by","of","this",
    "those","these","because","while","during","before","after","again","ever","never","always"
}

PROVIDER_KEYS = {
    "pexels": ("PEXELS_API_KEY",),
    "pixabay": ("PIXABAY_API_KEY",),
    "unsplash": ("UNSPLASH_ACCESS_KEY", "UNSPLASH_KEY"),
}

def get_secret(*names, default=""):
    for name in names:
        try:
            if name in st.secrets:
                value = st.secrets.get(name)
                if value:
                    return str(value)
        except Exception:
            pass
        value = os.getenv(name)
        if value:
            return value
    return default

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    return name[:80] or "output"

def ffmpeg_exists() -> bool:
    return shutil.which("ffmpeg") is not None

def ffprobe_exists() -> bool:
    return shutil.which("ffprobe") is not None

def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True,
        )
        return True, proc.stdout + proc.stderr
    except subprocess.CalledProcessError as e:
        return False, (e.stdout or "") + (e.stderr or "") + f"\n[exit code {e.returncode}]"
    except Exception as e:
        return False, str(e)

def srt_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    ms = int(round(seconds * 1000))
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text

def wrap_lyric(text: str, width: int = 34) -> str:
    text = clean_text(text)
    if not text:
        return ""
    return textwrap.fill(text, width=width)

def extract_keywords(text: str, limit: int = 4) -> str:
    words = re.findall(r"[A-Za-z']+", text.lower())
    ranked = []
    seen = set()
    for word in words:
        if len(word) < 4:
            continue
        if word in STOPWORDS:
            continue
        if word in seen:
            continue
        seen.add(word)
        ranked.append(word)
    if not ranked:
        return ""
    return " ".join(ranked[:limit])

def get_font_path() -> Optional[str]:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def create_gradient_image(path: Path, c1: str, c2: str, size=(VIDEO_W, VIDEO_H), vertical=False):
    img = Image.new("RGB", size, c1)
    draw = ImageDraw.Draw(img)
    w, h = size
    if vertical:
        for y in range(h):
            ratio = y / max(h - 1, 1)
            r1, g1, b1 = ImageColor_to_rgb(c1)
            r2, g2, b2 = ImageColor_to_rgb(c2)
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            draw.line((0, y, w, y), fill=(r, g, b))
    else:
        for x in range(w):
            ratio = x / max(w - 1, 1)
            r1, g1, b1 = ImageColor_to_rgb(c1)
            r2, g2, b2 = ImageColor_to_rgb(c2)
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            draw.line((x, 0, x, h), fill=(r, g, b))
    img.save(path)

def ImageColor_to_rgb(color: str):
    color = color.strip()
    if not color.startswith("#"):
        color = "#" + color
    return ImageColor_getrgb(color)

def ImageColor_getrgb(color):
    from PIL import ImageColor
    return ImageColor.getrgb(color)

def create_solid_image(path: Path, color: str, size=(VIDEO_W, VIDEO_H)):
    Image.new("RGB", size, color).save(path)

def fit_image_to_video(src: Path, dst: Path, size=(VIDEO_W, VIDEO_H)):
    img = Image.open(src).convert("RGB")
    img = ImageOps.fit(img, size, method=Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(radius=0))
    img.save(dst)

def make_intro_card(path: Path, title: str, artist: str, bg_color: str, text_color: str,
                    bg_image: Optional[Path] = None, gradient: Optional[Tuple[str, str]] = None):
    if bg_image and bg_image.exists():
        img = Image.open(bg_image).convert("RGB")
        img = ImageOps.fit(img, (VIDEO_W, VIDEO_H), method=Image.Resampling.LANCZOS)
    elif gradient:
        img = Image.new("RGB", (VIDEO_W, VIDEO_H), gradient[0])
        draw = ImageDraw.Draw(img)
        r1, g1, b1 = ImageColor_to_rgb(gradient[0])
        r2, g2, b2 = ImageColor_to_rgb(gradient[1])
        for x in range(VIDEO_W):
            ratio = x / max(VIDEO_W - 1, 1)
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            draw.line((x, 0, x, VIDEO_H), fill=(r, g, b))
    else:
        img = Image.new("RGB", (VIDEO_W, VIDEO_H), bg_color)
    draw = ImageDraw.Draw(img)
    font_path = get_font_path()
    title_font = ImageFont.truetype(font_path, 64) if font_path else ImageFont.load_default()
    artist_font = ImageFont.truetype(font_path, 36) if font_path else ImageFont.load_default()

    # subtle overlay
    overlay = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 90))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(img)
    title_box = draw.multiline_textbbox((0, 0), title, font=title_font, spacing=10, align="center")
    artist_box = draw.multiline_textbbox((0, 0), artist, font=artist_font, spacing=8, align="center")
    total_h = (title_box[3] - title_box[1]) + 26 + (artist_box[3] - artist_box[1])
    y = (VIDEO_H - total_h) // 2
    draw.multiline_text(((VIDEO_W) / 2, y), title, font=title_font, fill=text_color, anchor="ma", align="center", spacing=10)
    draw.multiline_text(((VIDEO_W) / 2, y + (title_box[3] - title_box[1]) + 26), artist, font=artist_font, fill=text_color, anchor="ma", align="center", spacing=8)
    img.convert("RGB").save(path, quality=95)

def create_lyric_card(path: Path, text: str, text_color: str, font_size: int,
                      bg_color: str = "#000000", bg_image: Optional[Path] = None,
                      gradient: Optional[Tuple[str, str]] = None,
                      align: str = "center"):
    if bg_image and bg_image.exists():
        img = Image.open(bg_image).convert("RGB")
        img = ImageOps.fit(img, (VIDEO_W, VIDEO_H), method=Image.Resampling.LANCZOS)
    elif gradient:
        img = Image.new("RGB", (VIDEO_W, VIDEO_H), gradient[0])
        draw = ImageDraw.Draw(img)
        r1, g1, b1 = ImageColor_to_rgb(gradient[0])
        r2, g2, b2 = ImageColor_to_rgb(gradient[1])
        for x in range(VIDEO_W):
            ratio = x / max(VIDEO_W - 1, 1)
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            draw.line((x, 0, x, VIDEO_H), fill=(r, g, b))
    else:
        img = Image.new("RGB", (VIDEO_W, VIDEO_H), bg_color)

    overlay = Image.new("RGBA", (VIDEO_W, VIDEO_H), (0, 0, 0, 100))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)

    draw = ImageDraw.Draw(img)
    font_path = get_font_path()
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
    wrapped = wrap_lyric(text, 32)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align=align, spacing=12, stroke_width=2)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (VIDEO_W - tw) // 2
    y = int(VIDEO_H * 0.58 - th / 2)
    draw.rounded_rectangle((x - 40, y - 28, x + tw + 40, y + th + 28), radius=24, fill=(0, 0, 0, 120))
    draw.multiline_text((VIDEO_W // 2, y), wrapped, font=font, fill=text_color, align="center", spacing=12, anchor="ma", stroke_width=2, stroke_fill=(0,0,0))
    img.convert("RGB").save(path, quality=95)

def safe_download_image(url: str, out_path: Path, timeout=20) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return True
    except Exception:
        return False

def search_pexels(query: str, api_key: str) -> Optional[str]:
    if not api_key:
        return None
    try:
        url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": api_key}
        params = {"query": query, "per_page": 1, "orientation": "landscape"}
        r = requests.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        photos = data.get("photos") or []
        if not photos:
            return None
        src = photos[0]["src"]
        return src.get("large2x") or src.get("large") or src.get("original")
    except Exception:
        return None

def search_pixabay(query: str, api_key: str) -> Optional[str]:
    if not api_key:
        return None
    try:
        url = "https://pixabay.com/api/"
        params = {"key": api_key, "q": query, "image_type": "photo", "orientation": "horizontal", "per_page": 3, "safesearch": "true"}
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        hits = data.get("hits") or []
        if not hits:
            return None
        return hits[0].get("largeImageURL") or hits[0].get("webformatURL")
    except Exception:
        return None

def search_unsplash(query: str, access_key: str) -> Optional[str]:
    if not access_key:
        return None
    try:
        url = "https://api.unsplash.com/search/photos"
        headers = {"Authorization": f"Client-ID {access_key}"}
        params = {"query": query, "per_page": 1, "orientation": "landscape"}
        r = requests.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None
        return results[0]["urls"]["regular"]
    except Exception:
        return None

def get_image_for_query(query: str, workdir: Path) -> Optional[Path]:
    query = clean_text(query)
    if not query:
        return None
    query = query[:80]
    api_keys = {
        "pexels": get_secret("PEXELS_API_KEY"),
        "pixabay": get_secret("PIXABAY_API_KEY"),
        "unsplash": get_secret("UNSPLASH_ACCESS_KEY", "UNSPLASH_KEY"),
    }
    providers = [
        ("pexels", search_pexels),
        ("pixabay", search_pixabay),
        ("unsplash", search_unsplash),
    ]
    for name, fn in providers:
        try:
            url = fn(query, api_keys[name])
            if url:
                out = workdir / f"{safe_filename(name + '_' + query)}.jpg"
                if safe_download_image(url, out):
                    return out
        except Exception:
            continue
    return None

def render_subtitle_file(path: Path, text: str, duration: float):
    with open(path, "w", encoding="utf-8") as f:
        f.write("1\n")
        f.write(f"00:00:00,000 --> {srt_time(duration)}\n")
        f.write(text.strip() + "\n")

def build_segment_ffmpeg(
    audio_path: Path,
    output_path: Path,
    subtitle_path: Path,
    duration: float,
    background_mode: str,
    font_size: int,
    text_color: str,
    bg_color: str,
    bg_image_path: Optional[Path] = None,
    visualizer_style: str = "wave",
):
    force_style = (
        f"FontName=DejaVu Sans Bold,FontSize={font_size},"
        f"PrimaryColour={color_to_ass_color(text_color)},OutlineColour=&H000000&,BackColour=&H66000000&,"
        f"Bold=1,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=80"
    )

    if background_mode == "equalizer":
        # generate audio-reactive visualizer from the clip audio
        if visualizer_style == "spectrum":
            filter_graph = (
                f"[0:a]showspectrum=s={VIDEO_W}x{VIDEO_H}:mode=combined:color=intensity:scale=lin:slide=scroll,format=yuv420p[v0];"
                f"[v0]subtitles={escape_filter_path(subtitle_path)}:force_style='{force_style}'[v1]"
            )
        elif visualizer_style == "cqt":
            filter_graph = (
                f"[0:a]showcqt=s={VIDEO_W}x{VIDEO_H}:fps={FPS},format=yuv420p[v0];"
                f"[v0]subtitles={escape_filter_path(subtitle_path)}:force_style='{force_style}'[v1]"
            )
        elif visualizer_style == "bars":
            filter_graph = (
                f"[0:a]showwaves=s={VIDEO_W}x{VIDEO_H}:mode=bar:rate={FPS},format=yuv420p[v0];"
                f"[v0]subtitles={escape_filter_path(subtitle_path)}:force_style='{force_style}'[v1]"
            )
        else:
            filter_graph = (
                f"[0:a]showwaves=s={VIDEO_W}x{VIDEO_H}:mode=line:rate={FPS},format=yuv420p[v0];"
                f"[v0]subtitles={escape_filter_path(subtitle_path)}:force_style='{force_style}'[v1]"
            )
        cmd = [
            "ffmpeg", "-y",
            "-ss", "0",
            "-t", f"{duration:.3f}",
            "-i", str(audio_path),
            "-filter_complex", filter_graph,
            "-map", "[v1]",
            "-map", "0:a",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_path),
        ]
    else:
        if bg_image_path and bg_image_path.exists():
            bg_input = bg_image_path
        else:
            bg_input = None
        if bg_input is None:
            tmp_bg = output_path.parent / "solid_bg.png"
            create_solid_image(tmp_bg, bg_color)
            bg_input = tmp_bg
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(bg_input),
            "-ss", "0",
            "-t", f"{duration:.3f}",
            "-i", str(audio_path),
            "-vf", f"subtitles={escape_filter_path(subtitle_path)}:force_style='{force_style}'",
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-r", str(FPS),
            str(output_path),
        ]
    ok, out = run_cmd(cmd)
    return ok, out

def color_to_ass_color(hex_color: str) -> str:
    # ASS uses &HAABBGGRR&
    hex_color = hex_color.strip().lstrip("#")
    if len(hex_color) != 6:
        hex_color = "FFFFFF"
    r = hex_color[0:2]
    g = hex_color[2:4]
    b = hex_color[4:6]
    return f"&H00{b}{g}{r}&"

def escape_filter_path(path: Path) -> str:
    p = str(path).replace("\\", "\\\\").replace(":", "\\:")
    return p

def transcribe_audio(audio_path: Path, model_name: str):
    model = load_whisper_model(model_name)
    return model.transcribe(str(audio_path), fp16=False)

@st.cache_resource
def load_whisper_model(model_name: str):
    return whisper.load_model(model_name)

def create_concat_list(paths: List[Path], out_path: Path):
    import shlex
    with open(out_path, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file {shlex.quote(str(p))}\n")

def concat_clips(clip_paths: List[Path], output_path: Path) -> Tuple[bool, str]:
    concat_list = output_path.parent / "concat_list.txt"
    create_concat_list(clip_paths, concat_list)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(output_path),
    ]
    ok, out = run_cmd(cmd)
    if ok:
        return ok, out

    # Fallback re-encode if stream copy fails
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path),
    ]
    return run_cmd(cmd)

def build_intro_clip(workdir: Path, title: str, artist: str, intro_seconds: int, settings: Dict, audio_path: Path) -> Optional[Path]:
    if intro_seconds <= 0:
        return None
    intro_img = workdir / "intro.png"
    bg_image = settings.get("intro_background_image")
    create_intro_card(
        intro_img,
        title=title or "Untitled Song",
        artist=artist or "Unknown Artist",
        bg_color=settings["bg_color"],
        text_color=settings["text_color"],
        bg_image=bg_image,
        gradient=settings.get("gradient"),
    )
    intro_audio = workdir / "intro_silence.mp3"
    # use a tiny segment of the song audio for a nicer audio-driven intro, but keep it optional
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=stereo",
        "-t", str(intro_seconds),
        "-q:a", "9",
        "-acodec", "libmp3lame",
        str(intro_audio),
    ]
    run_cmd(cmd)

    intro_mp4 = workdir / "intro.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(intro_img),
        "-i", str(intro_audio),
        "-t", str(intro_seconds),
        "-vf", "scale=1280:720,format=yuv420p",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        str(intro_mp4),
    ]
    ok, out = run_cmd(cmd)
    if not ok:
        return None
    return intro_mp4

def render_video(
    audio_path: Path,
    segments: List[Dict],
    workdir: Path,
    settings: Dict,
) -> Tuple[bool, str, Optional[Path], List[Path]]:
    clip_paths = []
    intro_clip = build_intro_clip(
        workdir=workdir,
        title=settings["song_title"],
        artist=settings["artist_name"],
        intro_seconds=settings["intro_seconds"],
        settings=settings,
        audio_path=audio_path,
    )
    if intro_clip:
        clip_paths.append(intro_clip)

    section_images = settings.get("section_images") or []
    auto_image_mode = settings["auto_images"]
    background_mode = settings["background_mode"]
    visualizer_style = settings["visualizer_style"]

    for idx, seg in enumerate(segments):
        start = max(0.0, float(seg["start"]) + settings["sync_offset"])
        end = max(start + 0.1, float(seg["end"]) + settings["sync_offset"])
        duration = max(0.2, end - start)
        lyric = clean_text(seg["text"])
        if not lyric:
            continue

        seg_audio = workdir / f"segment_{idx:03d}.mp3"
        seg_clip = workdir / f"segment_{idx:03d}.mp4"
        sub_path = workdir / f"segment_{idx:03d}.srt"

        extract_ok, extract_out = run_cmd([
            "ffmpeg", "-y",
            "-ss", f"{start:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(audio_path),
            "-vn",
            "-acodec", "libmp3lame",
            str(seg_audio),
        ])
        if not extract_ok:
            # Skip bad segment rather than killing the whole render
            continue

        bg_path = None
        if idx < len(section_images) and section_images[idx]:
            bg_path = section_images[idx]
        elif auto_image_mode:
            q = extract_keywords(lyric, limit=4)
            if q:
                bg_path = get_image_for_query(q, workdir)

        if background_mode == "image" and not bg_path:
            bg_path = settings.get("fallback_image")

        if background_mode in {"solid", "gradient", "image"}:
            if background_mode == "solid":
                if bg_path and bg_path.exists():
                    # user uploaded a background image wins if selected and available
                    pass
                else:
                    bg = workdir / f"bg_{idx:03d}.png"
                    create_solid_image(bg, settings["bg_color"])
                    bg_path = bg
            elif background_mode == "gradient":
                bg = workdir / f"bg_{idx:03d}.png"
                create_gradient_image(bg, settings["gradient"][0], settings["gradient"][1], vertical=settings["gradient_vertical"])
                bg_path = bg
            elif background_mode == "image":
                if bg_path and bg_path.exists():
                    resized = workdir / f"bg_{idx:03d}.png"
                    fit_image_to_video(bg_path, resized)
                    bg_path = resized
                else:
                    bg = workdir / f"bg_{idx:03d}.png"
                    create_gradient_image(bg, settings["gradient"][0], settings["gradient"][1], vertical=settings["gradient_vertical"])
                    bg_path = bg

        render_subtitle_file(sub_path, lyric, duration)
        ok, out = build_segment_ffmpeg(
            audio_path=seg_audio,
            output_path=seg_clip,
            subtitle_path=sub_path,
            duration=duration,
            background_mode=background_mode if background_mode in {"equalizer"} else "static",
            font_size=settings["font_size"],
            text_color=settings["text_color"],
            bg_color=settings["bg_color"],
            bg_image_path=bg_path,
            visualizer_style=visualizer_style,
        )
        if not ok:
            # fallback to plain solid background if equalizer/render fails
            fallback_bg = workdir / f"fallback_{idx:03d}.png"
            create_solid_image(fallback_bg, settings["bg_color"])
            ok2, out2 = build_segment_ffmpeg(
                audio_path=seg_audio,
                output_path=seg_clip,
                subtitle_path=sub_path,
                duration=duration,
                background_mode="static",
                font_size=settings["font_size"],
                text_color=settings["text_color"],
                bg_color=settings["bg_color"],
                bg_image_path=fallback_bg,
                visualizer_style=visualizer_style,
            )
            if not ok2:
                continue
        clip_paths.append(seg_clip)

    output_path = workdir / "final_video.mp4"
    ok, out = concat_clips(clip_paths, output_path)
    if not ok:
        return False, out, None, clip_paths

    # Reattach full audio cleanly to final file in case concatenation lost audio sync
    final_mux = workdir / "final_video_mux.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(output_path),
        "-i", str(audio_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(final_mux),
    ]
    ok2, out2 = run_cmd(cmd)
    if ok2 and final_mux.exists():
        return True, out2, final_mux, clip_paths
    return True, out, output_path, clip_paths

def parse_segments(result, offset_sec: float = 0.0) -> List[Dict]:
    segments = []
    for seg in result.get("segments", []):
        txt = clean_text(seg.get("text", ""))
        if not txt:
            continue
        segments.append({
            "start": float(seg.get("start", 0.0)) + offset_sec,
            "end": float(seg.get("end", 0.0)) + offset_sec,
            "text": txt,
        })
    return segments

def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🎵", layout="wide")
    st.title("🎵 AI Lyric Video Generator")
    st.caption("Upload a song, transcribe the lyrics, customize the look, and download a YouTube-ready MP4.")

    if not ffmpeg_exists():
        st.error("FFmpeg is missing. Add it in packages.txt (or install it on your machine).")
        st.stop()

    with st.sidebar:
        st.header("Project settings")
        model_name = st.selectbox("Transcription model", ["tiny", "base", "small"], index=1)
        intro_seconds = st.slider("Intro screen length (seconds)", 0, 10, 3)
        sync_offset = st.slider("Lyric sync offset (seconds)", -3.0, 3.0, 0.0, 0.05)
        font_size = st.slider("Font size", 24, 96, 48)
        text_color = st.color_picker("Text color", "#FFFFFF")
        bg_mode = st.selectbox(
            "Background mode",
            ["solid", "gradient", "image", "equalizer"],
            format_func=lambda x: {
                "solid": "Solid color",
                "gradient": "Gradient",
                "image": "Uploaded/custom image",
                "equalizer": "Animated audio visualizer",
            }[x],
        )
        visualizer_style = st.selectbox(
            "Visualizer style",
            ["wave", "bars", "spectrum", "cqt"],
            format_func=lambda x: {
                "wave": "Wave line",
                "bars": "Audio bars",
                "spectrum": "Spectrum",
                "cqt": "Color music pulse",
            }[x],
        )
        bg_color = st.color_picker("Background base color", "#000000")
        gradient_a = st.color_picker("Gradient start", "#0B1020")
        gradient_b = st.color_picker("Gradient end", "#2B59FF")
        gradient_vertical = st.checkbox("Vertical gradient", value=False)
        auto_images = st.checkbox("Auto royalty-free images by lyric section", value=False)
        use_fallback_image = st.checkbox("Use uploaded image if image search fails", value=True)

    col1, col2 = st.columns([1.15, 0.85])

    with col1:
        audio_file = st.file_uploader("Upload original audio", type=["mp3", "wav", "m4a", "aac", "flac", "ogg"])
        title = st.text_input("Song title", value="")
        artist = st.text_input("Artist name", value="")
        intro_bg = st.file_uploader("Optional intro background image", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=False)
        bg_upload = st.file_uploader("Optional background image for the whole video", type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=False)
        section_images = st.file_uploader(
            "Optional custom images in order for lyric sections",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            help="Upload multiple images. The first image will be used for the first lyric section, the second image for the next section, and so on.",
        )
        if audio_file:
            st.audio(audio_file)

    with col2:
        st.subheader("What this app does")
        st.write(
            "- Transcribes the lyrics from your song with Whisper.\n"
            "- Burns synced lyrics into the video.\n"
            "- Lets you adjust timing, font size, colors, and background style.\n"
            "- Can use royalty-free image search as a fallback.\n"
            "- Exports a downloadable MP4 that is ready for YouTube upload."
        )
        st.info("GitHub repo secrets are not enough for a live app by themselves. Put secrets in the hosting platform where the app runs. The code also reads environment variables and Streamlit secrets, so it works locally and on hosted Streamlit apps.")

    st.divider()

    with st.expander("Advanced options", expanded=False):
        st.write("Optional API keys for image search. The app will try Pexels first, then Pixabay, then Unsplash. If one fails, it skips it and keeps rendering.")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.text_input("PEXELS_API_KEY present?", value="yes" if get_secret("PEXELS_API_KEY") else "no", disabled=True)
        with c2:
            st.text_input("PIXABAY_API_KEY present?", value="yes" if get_secret("PIXABAY_API_KEY") else "no", disabled=True)
        with c3:
            st.text_input("UNSPLASH_ACCESS_KEY present?", value="yes" if get_secret("UNSPLASH_ACCESS_KEY", "UNSPLASH_KEY") else "no", disabled=True)

        st.caption("Optional extras: GROQ_API_KEY is not required for this build. Whisper runs locally in the app. If you want a later cloud transcription fallback, Groq can be added, but it is not needed now.")

    if st.button("Generate lyric video", type="primary", disabled=audio_file is None):
        if not audio_file:
            st.warning("Please upload an audio file first.")
            st.stop()

        workdir = Path(tempfile.mkdtemp(prefix="lyric_video_"))
        try:
            audio_path = workdir / safe_filename(audio_file.name)
            audio_path.write_bytes(audio_file.getbuffer())

            intro_bg_path = None
            if intro_bg is not None:
                intro_bg_path = workdir / f"intro_{safe_filename(intro_bg.name)}"
                intro_bg_path.write_bytes(intro_bg.getbuffer())

            whole_bg_path = None
            if bg_upload is not None:
                whole_bg_path = workdir / f"bg_{safe_filename(bg_upload.name)}"
                whole_bg_path.write_bytes(bg_upload.getbuffer())

            sec_paths = []
            for f in section_images:
                p = workdir / f"section_{safe_filename(f.name)}"
                p.write_bytes(f.getbuffer())
                sec_paths.append(p)

            settings = {
                "song_title": title.strip(),
                "artist_name": artist.strip(),
                "intro_seconds": intro_seconds,
                "sync_offset": sync_offset,
                "font_size": font_size,
                "text_color": text_color,
                "bg_color": bg_color,
                "background_mode": bg_mode,
                "visualizer_style": visualizer_style,
                "auto_images": auto_images,
                "section_images": sec_paths,
                "intro_background_image": intro_bg_path,
                "fallback_image": whole_bg_path if use_fallback_image else None,
                "gradient": (gradient_a, gradient_b),
                "gradient_vertical": gradient_vertical,
            }

            st.info("Transcribing audio into lyric timing. This may take a little while on CPU.")
            with st.spinner("Loading transcription model..."):
                result = transcribe_audio(audio_path, model_name)
            segments = parse_segments(result, offset_sec=0.0)

            if not segments:
                st.error("No lyrics were detected. Try a different Whisper model or a clearer vocal mix.")
                st.stop()

            st.success(f"Found {len(segments)} lyric sections.")

            with st.spinner("Rendering video clips..."):
                ok, log, final_path, clips = render_video(audio_path, segments, workdir, settings)

            if not ok or final_path is None or not final_path.exists():
                st.error("Render failed, but the app kept going instead of crashing.")
                with st.expander("Render log"):
                    st.code(log[-12000:] if log else "No output")
                st.stop()

            st.success("Video created.")
            st.video(str(final_path))
            with open(final_path, "rb") as f:
                st.download_button(
                    "Download MP4",
                    data=f,
                    file_name=f"{safe_filename(title or audio_file.name)}_lyric_video.mp4",
                    mime="video/mp4",
                )

            with st.expander("Detected lyric sections"):
                for i, seg in enumerate(segments[:200], start=1):
                    st.write(f"{i}. {seg['start']:.2f}s → {seg['end']:.2f}s | {seg['text']}")

            with st.expander("If you want stronger results next time"):
                st.write(
                    "- Use a cleaner vocal mix for better transcription.\n"
                    "- Upload a few custom images so each lyric section has its own look.\n"
                    "- Keep the sync slider small unless the whole song is shifted.\n"
                    "- Use the spectrum or bars visualizer for a more modern motion look."
                )

        except Exception as e:
            st.error("Something went wrong, but the app handled it without taking down the whole page.")
            st.exception(e)

if __name__ == "__main__":
    main()

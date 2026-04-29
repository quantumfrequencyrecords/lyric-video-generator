import streamlit as st
import whisper
import subprocess
import os
from PIL import Image
import requests

st.title("🎵 AI Lyric Video Generator")

# Upload audio
audio_file = st.file_uploader("Upload your song", type=["mp3", "wav"])

# Song info
title = st.text_input("Song Title")
artist = st.text_input("Artist Name")
intro_duration = st.slider("Intro screen duration (seconds)", 1, 10, 3)

bg_color = st.color_picker("Background Color", "#000000")
text_color = st.color_picker("Text Color", "#FFFFFF")
font_size = st.slider("Font Size", 20, 80, 40)

use_images = st.checkbox("Auto background images (Pexels/Pixabay)")
use_wave = st.checkbox("Use audio visualizer background")

if audio_file:
    with open("input.mp3", "wb") as f:
        f.write(audio_file.read())

    st.success("Audio uploaded!")

    if st.button("Generate Lyrics + Video"):
        st.write("Transcribing lyrics...")

        model = whisper.load_model("base")
        result = model.transcribe("input.mp3")

        with open("lyrics.srt", "w") as f:
            for i, seg in enumerate(result["segments"]):
                f.write(f"{i+1}\n")
                f.write(f"{seg['start']} --> {seg['end']}\n")
                f.write(seg["text"] + "\n\n")

        st.write("Creating video...")

        cmd = f"""
        ffmpeg -y -loop 1 -i background.jpg -i input.mp3 \
        -vf "subtitles=lyrics.srt:force_style='Fontsize={font_size},PrimaryColour=&HFFFFFF&'" \
        -c:v libx264 -c:a aac -shortest output.mp4
        """

        subprocess.call(cmd, shell=True)

        st.success("Video created!")
        st.video("output.mp4")

        with open("output.mp4", "rb") as f:
            st.download_button("Download Video", f, file_name="lyric_video.mp4")

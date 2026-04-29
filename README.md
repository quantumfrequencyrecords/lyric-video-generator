# AI Lyric Video Generator

A free Streamlit app that takes an uploaded audio file, transcribes lyrics with Whisper, and renders a downloadable YouTube-ready MP4 lyric video.

## What it can do
- Upload original audio
- Transcribe lyrics locally with Whisper
- Apply a global sync offset
- Choose solid, gradient, uploaded image, or audio visualizer backgrounds
- Pick wave, bars, spectrum, or CQT visualizer styles
- Customize text color, background color, and font size
- Use uploaded images for the intro screen
- Use uploaded images per lyric section
- Optionally fetch royalty-free background images from Pexels, Pixabay, and Unsplash
- Fall back gracefully if any image provider fails

## Important note
GitHub repository secrets alone do **not** power a live web app. A running app needs secrets in the hosting platform too.

### Best free hosting path
- Put the repo on GitHub
- Deploy it as a Streamlit app on Hugging Face Spaces
- Add secrets in the Space settings

### GitHub-only reality
- GitHub Pages cannot run this app because it needs Python and FFmpeg
- GitHub Codespaces can be used for development, not as the public app
- GitHub Actions can automate tasks, but it is not the right place for an interactive upload-and-render web app

## Secrets
Set these where the app runs:
- `PEXELS_API_KEY`
- `PIXABAY_API_KEY`
- `UNSPLASH_ACCESS_KEY`

Optional:
- `UNSPLASH_KEY` as an alternate name
- `GROQ_API_KEY` is not required for this version

## Local run
```bash
pip install -r requirements.txt
# install ffmpeg on your computer
streamlit run app.py
```

## Deployment on Hugging Face Spaces
1. Create a new Space
2. Choose Streamlit
3. Connect your GitHub repo
4. Add the secrets above
5. Let the Space build
6. Open it from your phone and upload audio

## Tips
- Use short clips first while testing
- Use the `Wave line` or `Audio bars` visualizer for a modern motion look
- Add 2 to 10 custom section images for better visuals
- Keep the sync offset small unless the whole song is off

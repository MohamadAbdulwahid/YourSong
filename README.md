# YourSong 🎵

**Find more of the music you love—starting with your favorite few seconds.**

A music discovery app that identifies a song, finds related tracks, and uses Google's Gemini AI to discover similar musical moments. Those moments are stitched into a personalized mix with smooth transitions.

## Highlights

- **Song recognition:** identify uploaded audio with Shazam.
- **Music discovery:** explore related tracks through YouTube Music.
- **AI-powered matching:** find segments similar to your favorite part.
- **Personalized mixes:** combine matching segments into a downloadable MP3.
- **Live feedback:** follow background processing and explore a visual segment timeline.

## Tech stack

Python · Flask · Google Gemini · ShazamIO · YouTube Music API · NumPy · SciPy · Pydub · yt-dlp · HTML/CSS/JavaScript

## Run locally

Recommended: **Python 3.10–3.11**, with [FFmpeg](https://ffmpeg.org/) installed and available on your PATH.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file:

```dotenv
GEMINI_API_KEY=your_api_key
SECRET_KEY=your_random_secret_key
```

```bash
python app.py
```

Open **http://localhost:5000**, upload a song, and select your favorite segment.

> Experimental project. External music services and model availability may change. Only process audio you have permission to use.

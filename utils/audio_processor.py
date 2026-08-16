import os
import re
import shutil
from urllib.parse import parse_qs, urlparse

import yt_dlp
from pydub import AudioSegment

DOWNLOAD_DIR = 'downloades'
os.makedirs(DOWNLOAD_DIR,exist_ok = True)


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    cleaned = cleaned.replace('：', '_').replace(':', '_')
    cleaned = cleaned.strip().strip('.')
    return cleaned or 'audio'


def normalize_youtube_url(source: str) -> str:
    """Return a clean YouTube URL from raw/markdown/corrupted input."""
    raw = (source or "").strip()
    if not raw:
        return raw

    # Extract explicit markdown link target: [text](url)
    md_match = re.search(r"\[[^\]]+\]\((https?://[^)\s]+)\)", raw)
    if md_match:
        raw = md_match.group(1)

    # If the full URL is embedded in text, grab it.
    url_match = re.search(r"https?://\S+", raw)
    if url_match:
        raw = url_match.group(0)

    # Trim punctuation commonly attached during copy/paste.
    raw = raw.strip("<>()[]{}\"'.,;\n\r\t ")

    # Repair malformed host like 'www.youtube.comhttps'.
    raw = re.sub(r"youtube\.comhttps", "youtube.com", raw, flags=re.IGNORECASE)

    # Standardize short/long youtube URLs when possible.
    parsed = urlparse(raw)
    host = parsed.netloc.lower()

    if host in {"youtu.be"}:
        video_id = parsed.path.strip("/")
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"

    if "youtube.com" in host:
        query = parse_qs(parsed.query)
        video_id = query.get("v", [None])[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        if parsed.path.startswith("/shorts/"):
            short_id = parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
            if short_id:
                return f"https://www.youtube.com/watch?v={short_id}"

    return raw


def get_ffmpeg_bin_dir() -> str | None:
    candidates = [
        os.environ.get("FFMPEG_BIN"),
        os.environ.get("FFMPEG_PATH"),
        os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft",
            "WinGet",
            "Packages",
            "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
            "ffmpeg-9.0-full_build",
            "bin",
        ),
        r"C:\Users\Khushi Singh\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0-full_build\bin",
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files (x86)\ffmpeg\bin",
    ]

    for path in candidates:
        if not path:
            continue
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "ffmpeg.exe")):
            return path

    return None


def ensure_ffmpeg_available() -> str | None:
    """Ensure ffmpeg is visible to subprocess calls used by Whisper and pydub."""
    ffmpeg_dir = get_ffmpeg_bin_dir()
    if not ffmpeg_dir:
        return None

    ffmpeg_dir = os.path.normpath(ffmpeg_dir)
    ffmpeg_exe = os.path.join(ffmpeg_dir, "ffmpeg.exe")
    ffprobe_exe = os.path.join(ffmpeg_dir, "ffprobe.exe")

    os.environ["FFMPEG_BIN"] = ffmpeg_dir
    os.environ["FFMPEG_PATH"] = ffmpeg_dir

    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if ffmpeg_dir not in path_entries:
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    if os.path.exists(ffmpeg_exe):
        shutil.which("ffmpeg")
        AudioSegment.converter = ffmpeg_exe
        AudioSegment.ffmpeg = ffmpeg_exe
    if os.path.exists(ffprobe_exe):
        AudioSegment.ffprobe = ffprobe_exe

    return ffmpeg_dir


ensure_ffmpeg_available()


def download_youtube_audio(url :str) ->str:
    url = normalize_youtube_url(url)
    output_path = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
    ffmpeg_dir = get_ffmpeg_bin_dir()
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["web", "android"]}},
    }
    if ffmpeg_dir:
        ydl_opts["ffmpeg_location"] = ffmpeg_dir
        ydl_opts["ffprobe_location"] = ffmpeg_dir

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = sanitize_filename((info or {}).get("title") or "audio")
            filename = ydl.prepare_filename(info).replace(".webm", ".wav").replace(".m4a", ".wav")
            if os.path.exists(filename):
                return filename

            wav_candidates = [
                os.path.join(DOWNLOAD_DIR, f"{title}.wav"),
                os.path.join(DOWNLOAD_DIR, f"{title}_converted.wav"),
                os.path.splitext(filename)[0] + ".wav",
            ]
            for candidate in wav_candidates:
                if os.path.exists(candidate):
                    return candidate

        raise FileNotFoundError(
            f"YouTube audio download did not create a file for: {url}. "
            "This usually means the video is private, blocked, or YouTube rejected the request."
        )
    except yt_dlp.utils.DownloadError as exc:
        raise RuntimeError(
            f"Unable to download video data from YouTube: {exc}. "
            "The video may be restricted, private, or blocked for this environment."
        ) from exc



def convert_to_wav(input_path: str) -> str:
    """Convert any audio/video file to WAV format using pydub."""
    output_path = os.path.splitext(input_path)[0] + "_converted.wav"
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_channels(1).set_frame_rate(16000) #16khz
    audio.export(output_path, format="wav")
    return output_path



def chunk_audio(wav_path : str , chunk_minutes : int = 10) -> list:
    audio = AudioSegment.from_wav(wav_path)
    chunk_ms = chunk_minutes * 60 * 1000 

    chunks = []

    for i, start in enumerate(range(0,len(audio),chunk_ms)):
        chunk = audio[start : start + chunk_ms]
        chunk_path = f"{wav_path}_chunk_{i}.wav"
        chunk.export(chunk_path , format = "wav")

        chunks.append(chunk_path)
    
    return chunks

def process_input(source: str) -> list:
    try:
        if source.startswith("http://") or source.startswith("https://"):
            print("Detected YouTube URL. Downloading audio...")
            wav_path = download_youtube_audio(source)
        else:
            print("Detected local file. Converting to WAV...")
            wav_path = convert_to_wav(source)

        if not os.path.exists(wav_path):
            raise FileNotFoundError(f"Audio file was not created: {wav_path}")

        print("Chunking audio...")
        chunks = chunk_audio(wav_path)
        print(f"Audio ready — {len(chunks)} chunk(s) created.")
        return chunks
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Input file not found or download failed: {source}. "
            "Please verify the video URL or use a local audio/video file."
        ) from exc



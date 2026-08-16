import os
import shutil

from utils.audio_processor import ensure_ffmpeg_available, get_ffmpeg_bin_dir


def test_ensure_ffmpeg_available_adds_ffmpeg_dir_to_path():
    ffmpeg_dir = get_ffmpeg_bin_dir()
    assert ffmpeg_dir is not None, "FFmpeg should be discoverable on this machine."

    resolved = ensure_ffmpeg_available()
    assert resolved == ffmpeg_dir
    assert shutil.which("ffmpeg") == os.path.join(ffmpeg_dir, "ffmpeg.exe")

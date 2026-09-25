import os
import sys
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from PIL import Image

WIN_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

try:
    import imageio_ffmpeg
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG_EXE = shutil.which("ffmpeg")


def get_ffmpeg_path() -> Optional[str]:
    """Return valid FFmpeg binary path."""
    if FFMPEG_EXE and os.path.isfile(FFMPEG_EXE):
        return FFMPEG_EXE
    found = shutil.which("ffmpeg")
    return found


def is_image_file(path: str | Path) -> bool:
    """Check if file is supported image format."""
    ext = Path(path).suffix.lower()
    return ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def is_video_file(path: str | Path) -> bool:
    """Check if file is supported video format."""
    ext = Path(path).suffix.lower()
    return ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"}


def format_size(bytes_val: int) -> str:
    """Format bytes to human readable string."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def get_media_info(file_path: str | Path) -> Dict[str, Any]:
    """
    Inspect media file and return metadata dictionary:
    type: 'image' or 'video'
    width, height, size_str, etc.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    size_bytes = path.stat().st_size
    info: Dict[str, Any] = {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.lower(),
        "size_bytes": size_bytes,
        "size_str": format_size(size_bytes),
    }

    if is_image_file(path):
        info["type"] = "image"
        with Image.open(path) as img:
            info["width"] = img.width
            info["height"] = img.height
            info["format"] = img.format or path.suffix.upper().lstrip(".")
            info["aspect_ratio"] = f"{img.width}:{img.height}"
        return info

    if is_video_file(path):
        info["type"] = "video"
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            info["width"] = 0
            info["height"] = 0
            info["fps"] = 30.0
            info["duration"] = 0.0
            info["has_audio"] = False
            return info

        # Run ffmpeg -i to parse stderr video/audio streams
        try:
            cmd = [ffmpeg, "-hide_banner", "-i", str(path)]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                creationflags=WIN_NO_WINDOW,
            )
            output = proc.stderr

            # Parse resolution: look for pattern like 1920x1080
            res_match = re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", output)
            if res_match:
                info["width"] = int(res_match.group(1))
                info["height"] = int(res_match.group(2))
            else:
                res_match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", output)
                if res_match:
                    info["width"] = int(res_match.group(1))
                    info["height"] = int(res_match.group(2))
                else:
                    info["width"] = 0
                    info["height"] = 0

            # Parse fps: try 'fps', then fallback to 'tbr' (common in WebM)
            fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", output)
            if not fps_match:
                fps_match = re.search(r"(\d+(?:\.\d+)?)\s*tbr", output)
            if fps_match:
                info["fps"] = float(fps_match.group(1))
            else:
                info["fps"] = 30.0


            # Parse duration (e.g. Duration: 00:01:23.45)
            dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", output)
            if dur_match:
                hours = int(dur_match.group(1))
                mins = int(dur_match.group(2))
                secs = float(dur_match.group(3))
                total_secs = hours * 3600 + mins * 60 + secs
                info["duration"] = total_secs
                info["duration_str"] = format_duration(total_secs)
                info["estimated_frames"] = max(1, int(total_secs * info["fps"]))
            else:
                info["duration"] = 0.0
                info["duration_str"] = "00:00"
                info["estimated_frames"] = 0

            # Check for audio stream
            info["has_audio"] = bool(re.search(r"Audio:", output))

        except Exception as e:
            info["width"] = 0
            info["height"] = 0
            info["fps"] = 30.0
            info["duration"] = 0.0
            info["has_audio"] = False

        return info

    raise ValueError(f"Unsupported media file format: {path.suffix}")


def clean_dir(dir_path: Path):
    """Safely remove a directory and its contents."""
    if dir_path.exists():
        try:
            shutil.rmtree(dir_path)
        except Exception:
            pass


_CACHED_ENCODER_CONFIG: Optional[Dict[str, Any]] = None


def get_best_video_encoder() -> Dict[str, Any]:
    """
    Detect the fastest available video encoder with hardware acceleration.
    Checks Intel QSV, NVIDIA NVENC, AMD AMF, and falls back to CPU libx264.
    Returns dict with 'name', 'codec', 'args', and 'is_hw'.
    """
    global _CACHED_ENCODER_CONFIG
    if _CACHED_ENCODER_CONFIG is not None:
        return _CACHED_ENCODER_CONFIG

    ffmpeg = get_ffmpeg_path()
    cpu_fallback = {
        "name": "CPU (libx264)",
        "codec": "libx264",
        "args": ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "medium", "-threads", "0"],
        "is_hw": False,
    }

    if not ffmpeg:
        _CACHED_ENCODER_CONFIG = cpu_fallback
        return cpu_fallback

    # Candidate hardware encoders in priority order
    candidates = [
        {
            "name": "Intel Quick Sync (h264_qsv)",
            "codec": "h264_qsv",
            "args": ["-c:v", "h264_qsv", "-global_quality", "20", "-preset", "faster", "-pix_fmt", "yuv420p"],
            "test_args": ["-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=10", "-c:v", "h264_qsv", "-global_quality", "20", "-pix_fmt", "yuv420p", "-f", "null", "-"],
            "is_hw": True,
        },
        {
            "name": "NVIDIA NVENC (h264_nvenc)",
            "codec": "h264_nvenc",
            "args": ["-c:v", "h264_nvenc", "-cq", "19", "-preset", "p5", "-pix_fmt", "yuv420p"],
            "test_args": ["-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=10", "-c:v", "h264_nvenc", "-cq", "19", "-pix_fmt", "yuv420p", "-f", "null", "-"],
            "is_hw": True,
        },
        {
            "name": "AMD AMF (h264_amf)",
            "codec": "h264_amf",
            "args": ["-c:v", "h264_amf", "-rc", "cqp", "-qp_p", "19", "-pix_fmt", "yuv420p"],
            "test_args": ["-f", "lavfi", "-i", "testsrc=duration=1:size=128x128:rate=10", "-c:v", "h264_amf", "-rc", "cqp", "-qp_p", "19", "-pix_fmt", "yuv420p", "-f", "null", "-"],
            "is_hw": True,
        },
    ]

    for cand in candidates:
        try:
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + cand["test_args"]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
                creationflags=WIN_NO_WINDOW,
            )
            if proc.returncode == 0:
                _CACHED_ENCODER_CONFIG = {
                    "name": cand["name"],
                    "codec": cand["codec"],
                    "args": cand["args"],
                    "is_hw": True,
                }
                return _CACHED_ENCODER_CONFIG
        except Exception:
            continue

    _CACHED_ENCODER_CONFIG = cpu_fallback
    return cpu_fallback


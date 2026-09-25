import os
import sys
import zipfile
import shutil
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = BASE_DIR / "bin"

# Official GitHub release assets
ENGINES = {
    "realesrgan": {
        "name": "Real-ESRGAN (NCNN-Vulkan)",
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip",
        "dir": BIN_DIR / "realesrgan-ncnn-vulkan",
        "exe": "realesrgan-ncnn-vulkan.exe",
        "test_arg": "-h",
    },
    "realcugan": {
        "name": "Real-CUGAN (NCNN-Vulkan)",
        "url": "https://github.com/nihui/realcugan-ncnn-vulkan/releases/download/20220728/realcugan-ncnn-vulkan-20220728-windows.zip",
        "dir": BIN_DIR / "realcugan-ncnn-vulkan",
        "exe": "realcugan-ncnn-vulkan.exe",
        "test_arg": "-h",
    },
    "rife": {
        "name": "RIFE Video Interpolation (NCNN-Vulkan)",
        "url": "https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/rife-ncnn-vulkan-20221029-windows.zip",
        "dir": BIN_DIR / "rife-ncnn-vulkan",
        "exe": "rife-ncnn-vulkan.exe",
        "test_arg": "-h",
    },
}


def get_engine_exe(engine_key: str) -> Optional[Path]:
    """Return path to executable if installed and valid."""
    info = ENGINES.get(engine_key)
    if not info:
        return None
    exe_path = info["dir"] / info["exe"]
    if exe_path.is_file():
        return exe_path
    return None


def is_engine_installed(engine_key: str) -> bool:
    """Check if the given engine is already installed."""
    exe = get_engine_exe(engine_key)
    return exe is not None and exe.exists()


def check_all_installed() -> dict[str, bool]:
    """Return dict of engine_key -> bool installed status."""
    return {k: is_engine_installed(k) for k in ENGINES}


def download_and_extract_engine(
    engine_key: str,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> bool:
    """
    Download and extract an engine zip into bin/<engine_name>.
    progress_callback(status_text, bytes_downloaded, total_bytes)
    """
    info = ENGINES.get(engine_key)
    if not info:
        raise ValueError(f"Unknown engine: {engine_key}")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target_dir = info["dir"]
    zip_path = BIN_DIR / f"{engine_key}.zip"

    url = info["url"]
    name = info["name"]

    try:
        if progress_callback:
            progress_callback(f"Connecting to download {name}...", 0, 100)

        # Download with chunking and progress
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
        with urllib.request.urlopen(req) as response, open(zip_path, "wb") as out_file:
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 1024 * 64  # 64 KB

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size > 0:
                    percent = int((downloaded / total_size) * 100)
                    progress_callback(
                        f"Downloading {name} ({downloaded // (1024 * 1024)}MB / {total_size // (1024 * 1024)}MB)...",
                        downloaded,
                        total_size,
                    )

        if progress_callback:
            progress_callback(f"Extracting {name}...", 100, 100)

        target_dir.mkdir(parents=True, exist_ok=True)

        # Extract archive
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(target_dir)

            # If extracted into target_dir/<subfolder>/exe, flatten to target_dir
            exe_subpaths = list(target_dir.glob(f"**/{info['exe']}"))
            if exe_subpaths:
                direct_dir = exe_subpaths[0].parent
                if direct_dir != target_dir:
                    for item in direct_dir.iterdir():
                        shutil.move(str(item), str(target_dir))
                    # Remove empty subdirs
                    for sub in list(target_dir.iterdir()):
                        if sub.is_dir() and not any(sub.iterdir()):
                            try:
                                sub.rmdir()
                            except OSError:
                                pass

        # Clean up zip file
        if zip_path.exists():
            zip_path.unlink()

        return is_engine_installed(engine_key)

    except Exception as e:
        if zip_path.exists():
            try:
                zip_path.unlink()
            except OSError:
                pass
        raise RuntimeError(f"Failed to download/extract {name}: {e}") from e


def download_all(progress_callback: Optional[Callable[[str, int, int], None]] = None):
    """Download all 3 engines sequentially."""
    for key in ENGINES:
        if not is_engine_installed(key):
            download_and_extract_engine(key, progress_callback)


if __name__ == "__main__":
    def print_progress(status, current, total):
        if total > 0:
            pct = int((current / total) * 100)
            print(f"[{pct:3d}%] {status}")
        else:
            print(status)

    print("Checking / Downloading engines...")
    download_all(print_progress)
    print("Engines status:", check_all_installed())

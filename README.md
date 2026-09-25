# Upscaler

A fast, lightweight desktop application for super-resolution image & video upscaling and object/watermark removal, accelerated by **NCNN-Vulkan** on your GPU (Intel Iris Xe, NVIDIA, AMD).

Runs **100% locally and completely offline** with zero subscriptions, zero cloud APIs, and zero data leaving your machine.

---

## Features

- **Local GPU Acceleration**: Runs native C++ NCNN binaries with Vulkan SPIR-V shaders directly on your GPU.
- **Batch Processing Queue**: Drag and drop single files, batches, or whole folders (PNG, JPG, WEBP, BMP, MP4, MKV, MOV, AVI). Full-height responsive queue with live item and batch progress.
- **AI Upscaling Models**:
  - **Real-ESRGAN Photo (4x)**: High-fidelity restoration for real-world photos, portraits, and textures.
  - **Real-ESRGAN Anime (4x)**: Specialized 2D illustration model preserving fine line art.
  - **Real-ESRGAN Video / Fast (2x, 3x, 4x)**: High-speed lightweight model with dedicated scaling factors.
  - **Real-CUGAN Anime (2x, 3x, 4x)**: Dedicated anime engine with customizable denoise levels (None to High).
  - **RIFE Video Motion (60fps)**: AI frame interpolation doubling video framerate (e.g. 24fps/30fps to smooth 60fps).
- **AI Object & Watermark Eraser**:
  - Inpainting studio with interactive brush painting, undo history, adjustable brush size, and live comparison.
  - Powered by **Big-LaMa** (general objects & text), **Manga-LaMa** (manga/anime bubbles & line art), **AOT-Inpainting** (fast contextual fills), and **OpenCV Telea** (instant local touch-ups).
  - Cleaned images can be sent directly back to the upscale queue with one click.
- **Interactive Visual Comparator**:
  - Side-by-side or draggable split-screen wipe slider with synchronized zoom & pan to inspect before/after differences.
- **Lossless Audio Preservation**:
  - Automatically extracts and re-muxes original audio tracks into upscaled videos via FFmpeg.
- **Clean Naming & Collision Avoidance**:
  - Embeds model tag and scale factor into output filenames (e.g. `image_realesrgan-x4plus_4x.png`) to prevent accidental overwrites.

---

## Quick Start

### 1. Launch the Application
Double-click `run.bat` or run from terminal:
```bash
.\.venv\Scripts\python main.py
```
*(Or via uv: `uv run main.py`)*

### 2. Basic Workflow
1. **Add Files**: Drop images or videos anywhere into the window, or click **Add Files...** / **Add Folder...**.
2. **Choose Settings**: Select the model engine, scale factor (2x, 3x, 4x), and destination folder.
3. **Upscale**: Click **Start Upscaling**.
4. **Compare**: Click **Compare** on any completed item or in the top bar to inspect before/after results with the split slider.

### 3. Object & Watermark Removal
1. Click **Object Eraser** in the top bar, or click **Erase** on any image in your queue.
2. Paint over unwanted text, watermarks, or objects with the brush.
3. Select your model (Big-LaMa, Manga-LaMa, AOT, or OpenCV) and click **Erase**.
4. Click **Send to Upscaler** to queue the cleaned image for super-resolution.

---

## Project Structure

```
Upscaler/
├── bin/                       # Local NCNN-Vulkan binaries & models
│   ├── realesrgan-ncnn-vulkan/
│   ├── realcugan-ncnn-vulkan/
│   └── rife-ncnn-vulkan/
├── src/
│   ├── app.py                 # Main PyQt6 desktop interface and queue management
│   ├── comparator.py          # Interactive split-slider and side-by-side comparison modal
│   ├── downloader.py          # NCNN engine verification and download helper
│   ├── eraser_dialog.py       # Object & watermark eraser studio with interactive canvas
│   ├── inpainter.py           # Neural inpainting engine (Big-LaMa, Manga-LaMa, AOT, OpenCV)
│   ├── processor.py           # Subprocess worker thread, FFmpeg pipeline, and output naming
│   ├── styles.py              # Dark theme styling and design tokens
│   └── utils.py               # Media probing (Pillow, FFmpeg) and format helpers
├── output/                    # Default destination for enhanced media
├── run.bat                    # Windows launcher (silent pythonw execution)
├── main.py                    # Application entry point
└── requirements.txt           # Python dependencies
```

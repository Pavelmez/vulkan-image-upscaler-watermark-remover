import os
import sys
import re
import time
import queue
import shutil
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from PyQt6.QtCore import QThread, pyqtSignal

from src.downloader import get_engine_exe
from src.utils import (
    get_media_info,
    get_ffmpeg_path,
    clean_dir,
    is_video_file,
    is_image_file,
    get_best_video_encoder,
)

WIN_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def get_model_tag(model_type: str, model_name: str, denoise: int = 0) -> str:
    """
    Generate clean, standardized model identifier for filenames and UI.
    e.g. 'realesrgan-x4plus', 'realesrgan-x4plus-anime', 'realcugan-se-c0', 'rife-v4'.
    """
    if model_type == "realesrgan":
        return model_name or "realesrgan-x4plus"
    elif model_type == "realcugan":
        denoise_map = {-1: "none", 0: "c0", 1: "dn1", 2: "dn2", 3: "dn3"}
        dn_suffix = denoise_map.get(denoise, f"dn{denoise}")
        return f"realcugan-se-{dn_suffix}"
    elif model_type == "rife":
        return model_name or "rife-v4"
    return model_type


def get_output_filename(
    input_path: Path | str,
    model_type: str,
    model_name: str,
    scale: int = 4,
    denoise: int = 0,
    custom_out_name: Optional[str] = None,
) -> str:
    """
    Compute clean output filename incorporating the model tag and upscale factor.
    e.g. 'photo_realesrgan-x4plus_4x.png' or 'anime_realcugan-se-c0_4x.png'.
    """
    if custom_out_name:
        return custom_out_name

    in_path = Path(input_path)
    stem = in_path.stem
    ext = in_path.suffix.lower()
    tag = get_model_tag(model_type, model_name, denoise)

    if is_video_file(in_path):
        suffix = f"_{scale}x" if model_type != "rife" else "_60fps"
        return f"{stem}_{tag}{suffix}.mp4"
    else:
        if ext in {".jpg", ".jpeg"}:
            ext = ".png"  # Lossless high quality
        return f"{stem}_{tag}_{scale}x{ext}"


def get_unique_output_path(output_dir: Path | str, filename: str) -> Path:
    """
    Ensure the output path does not overwrite an existing file by appending
    incrementing indices (_1, _2, etc.) if a file with the same name already exists.
    """
    out_dir = Path(output_dir)
    candidate = out_dir / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    ext = candidate.suffix
    counter = 1
    while True:
        new_name = f"{stem}_{counter}{ext}"
        new_candidate = out_dir / new_name
        if not new_candidate.exists():
            return new_candidate
        counter += 1


@dataclass
class QueueTask:
    """Represents a single media upscaling task in the batch queue."""
    task_id: str
    input_path: Path
    output_dir: Path
    model_type: str
    model_name: str
    scale: int = 4
    denoise: int = 0
    custom_out_name: Optional[str] = None
    output_path: Optional[str] = None
    status: str = "pending"  # pending, processing, completed, failed, cancelled
    error: Optional[str] = None


class BatchUpscaleWorker(QThread):
    """
    Background worker for processing multiple images/videos sequentially
    without blocking the UI.
    """
    item_started = pyqtSignal(int, int, str)       # index, total, item_name
    item_progress = pyqtSignal(int, int, str)      # index, percent (0-100), message
    item_finished = pyqtSignal(int, bool, str, str) # index, success, output_path, message
    batch_progress = pyqtSignal(int, int, int)     # done_count, total_count, overall_pct
    batch_finished = pyqtSignal(int, int, list)    # success_count, fail_count, results
    log_message = pyqtSignal(str)                  # real-time verbose log line

    def __init__(self, tasks: List[QueueTask]):
        super().__init__()
        self.tasks = tasks
        self._is_cancelled = False
        self._current_proc: Optional[subprocess.Popen] = None
        self._temp_dir: Optional[Path] = None

    def _log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {msg}"
        print(formatted, flush=True)
        self.log_message.emit(formatted)

    def cancel(self):
        """Cancel entire batch and kill active subprocess."""
        self._is_cancelled = True
        self._log("[Worker] Cancellation requested by user.")
        if self._current_proc and self._current_proc.poll() is None:
            try:
                self._current_proc.terminate()
                self._current_proc.kill()
            except Exception:
                pass
        if self._temp_dir:
            clean_dir(self._temp_dir)

    def run(self):
        total = len(self.tasks)
        success_count = 0
        fail_count = 0

        self._log(f"--- Starting batch execution: {total} item(s) in queue ---")

        for idx, task in enumerate(self.tasks):
            if self._is_cancelled:
                task.status = "cancelled"
                self._log("[Batch] Cancelled by user.")
                self.item_finished.emit(idx, False, "", "Batch cancelled by user.")
                continue

            task.status = "processing"
            self._log(f"[Task {idx + 1}/{total}] Processing: {task.input_path.name}")
            self.item_started.emit(idx, total, task.input_path.name)
            self.batch_progress.emit(idx, total, int((idx / max(1, total)) * 100))

            try:
                out_path = self._process_task(task, idx)
                if self._is_cancelled:
                    task.status = "cancelled"
                    self._log(f"[Task {idx + 1}/{total}] Cancelled by user.")
                    self.item_finished.emit(idx, False, "", "Cancelled.")
                    break

                task.status = "completed"
                task.output_path = str(out_path)
                success_count += 1
                self._log(f"[Task {idx + 1}/{total}] Completed successfully -> {out_path.name}")
                self.item_finished.emit(idx, True, str(out_path), f"Saved to {out_path.name}")
            except Exception as e:
                if self._is_cancelled:
                    task.status = "cancelled"
                    self._log(f"[Task {idx + 1}/{total}] Cancelled.")
                    self.item_finished.emit(idx, False, "", "Cancelled.")
                    break
                task.status = "failed"
                task.error = str(e)
                fail_count += 1
                self._log(f"[Error] Task {idx + 1}/{total} failed: {str(e)}")
                self.item_finished.emit(idx, False, "", f"Failed: {str(e)}")

        completed_count = success_count + fail_count
        self.batch_progress.emit(completed_count, total, 100 if completed_count == total else int((completed_count / max(1, total)) * 100))
        self._log(f"--- Batch finished: {success_count} succeeded, {fail_count} failed ---")
        self.batch_finished.emit(success_count, fail_count, self.tasks)

    def _process_task(self, task: QueueTask, idx: int) -> Path:
        task.output_dir.mkdir(parents=True, exist_ok=True)
        info = get_media_info(task.input_path)

        def report(pct: int, msg: str):
            self.item_progress.emit(idx, pct, msg)

        if info["type"] == "image":
            return self._process_image(task, info, report)
        elif info["type"] == "video":
            return self._process_video(task, info, report)
        else:
            raise RuntimeError(f"Unsupported media type: {info['type']}")

    def _process_image(self, task: QueueTask, info: Dict[str, Any], report) -> Path:
        report(5, "Preparing image...")
        self._log(f"[Image] Input: {task.input_path.name} ({info.get('width')}x{info.get('height')}, {info.get('size_str')})")

        out_name = get_output_filename(
            task.input_path,
            task.model_type,
            task.model_name,
            task.scale,
            task.denoise,
            task.custom_out_name,
        )
        out_path = get_unique_output_path(task.output_dir, out_name)

        exe = get_engine_exe(task.model_type)
        if not exe:
            raise RuntimeError(f"Engine {task.model_type} executable not found in bin/")

        if task.model_type == "realesrgan":
            cmd = [
                str(exe),
                "-i", str(task.input_path),
                "-o", str(out_path),
                "-s", str(task.scale),
                "-n", task.model_name,
                "-m", str(exe.parent / "models"),
                "-j", "2:2:2",
                "-g", "0",
                "-v",
            ]
        elif task.model_type == "realcugan":
            cmd = [
                str(exe),
                "-i", str(task.input_path),
                "-o", str(out_path),
                "-s", str(task.scale),
                "-n", str(task.denoise),
                "-m", str(exe.parent / "models-se"),
                "-j", "2:2:2",
                "-g", "0",
                "-v",
            ]
        elif task.model_type == "rife":
            raise RuntimeError("RIFE model is designed for video frame interpolation, not static image upscaling.")
        else:
            raise ValueError(f"Unknown model type: {task.model_type}")

        model_label = get_model_tag(task.model_type, task.model_name, task.denoise)
        report(10, f"Upscaling with {model_label}...")
        self._log(f"[Engine] Starting {model_label} (Scale: {task.scale}x) on GPU device 0")
        self._log(f"[Command] {' '.join(cmd)}")

        self._current_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            cwd=str(exe.parent),
            creationflags=WIN_NO_WINDOW,
            bufsize=1,
        )

        q: queue.Queue = queue.Queue()
        def reader():
            try:
                for line in iter(self._current_proc.stdout.readline, ''):
                    q.put(line)
            except Exception:
                pass
            finally:
                try:
                    self._current_proc.stdout.close()
                except Exception:
                    pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        full_output = []
        pct_pattern = re.compile(r"(\d+(?:\.\d+)?)%")

        while self._current_proc.poll() is None or not q.empty():
            if self._is_cancelled:
                try:
                    self._current_proc.kill()
                except Exception:
                    pass
                break
            try:
                while True:
                    line = q.get_nowait()
                    line_clean = line.strip()
                    if not line_clean:
                        continue
                    full_output.append(line_clean)
                    self._log(f"[{model_label}] {line_clean}")
                    m = pct_pattern.search(line_clean)
                    if m:
                        try:
                            val = float(m.group(1))
                            ui_pct = int(10 + (val / 100.0) * 85)
                            ui_pct = max(10, min(95, ui_pct))
                            report(ui_pct, f"Upscaling with {model_label}... ({val:.1f}%)")
                        except ValueError:
                            pass
            except queue.Empty:
                pass
            time.sleep(0.04)

        if self._is_cancelled:
            if out_path.exists():
                out_path.unlink()
            raise RuntimeError("Cancelled by user.")

        if self._current_proc.returncode != 0:
            err_summary = "\n".join(full_output[-10:])
            raise RuntimeError(f"Engine error (code {self._current_proc.returncode}):\n{err_summary}")

        if not out_path.exists():
            raise RuntimeError("Output image was not created.")

        self._log(f"[Engine] Success! Output saved to: {out_path.name}")
        report(100, "Done!")
        return out_path

    def _process_video(self, task: QueueTask, info: Dict[str, Any], report) -> Path:
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            raise RuntimeError("FFmpeg executable not found. Cannot process video.")

        timestamp = int(time.time() * 1000)
        self._temp_dir = (Path(task.output_dir) / f"_temp_{timestamp}").resolve()
        frames_in_dir = self._temp_dir / "frames_in"
        frames_out_dir = self._temp_dir / "frames_out"
        audio_file = self._temp_dir / "audio.m4a"

        self._temp_dir.mkdir(parents=True, exist_ok=True)
        frames_in_dir.mkdir(parents=True, exist_ok=True)
        frames_out_dir.mkdir(parents=True, exist_ok=True)

        try:
            out_name = get_output_filename(
                task.input_path,
                task.model_type,
                task.model_name,
                task.scale,
                task.denoise,
                task.custom_out_name,
            )
            out_path = get_unique_output_path(task.output_dir, out_name)
            self._log(f"[Video] Input: {task.input_path.name} ({info.get('width')}x{info.get('height')} @ {info.get('fps')}fps, {info.get('duration_str')})")

            has_audio = info.get("has_audio", False)
            if has_audio:
                report(2, "Extracting audio track...")
                self._log(f"[FFmpeg] Extracting audio stream...")
                audio_cmd = [
                    ffmpeg, "-y", "-i", str(task.input_path),
                    "-vn", "-c:a", "copy", str(audio_file)
                ]
                p_audio = subprocess.run(
                    audio_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=WIN_NO_WINDOW
                )
                if p_audio.returncode != 0 or not audio_file.exists() or audio_file.stat().st_size == 0:
                    if audio_file.exists():
                        try:
                            audio_file.unlink()
                        except Exception:
                            pass
                    self._log("[FFmpeg] Transcoding audio cleanly to AAC 192k...")
                    audio_cmd = [
                        ffmpeg, "-y", "-i", str(task.input_path),
                        "-vn", "-c:a", "aac", "-b:a", "192k", str(audio_file)
                    ]
                    subprocess.run(
                        audio_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=WIN_NO_WINDOW
                    )

            if self._is_cancelled:
                raise RuntimeError("Cancelled by user.")

            report(5, "Extracting video frames (multi-threaded)...")
            self._log(f"[FFmpeg] Extracting video frames...")
            extract_cmd = [
                ffmpeg, "-y", "-i", str(task.input_path),
                "-threads", "0",
                "-qscale:v", "1",
                str(frames_in_dir / "%08d.png")
            ]
            self._current_proc = subprocess.Popen(
                extract_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                creationflags=WIN_NO_WINDOW
            )
            _, extract_err = self._current_proc.communicate()

            if self._is_cancelled:
                raise RuntimeError("Cancelled by user.")

            extracted_frames = sorted(list(frames_in_dir.glob("*.png")))
            total_frames = len(extracted_frames)
            if total_frames == 0:
                raise RuntimeError("Failed to extract frames from video.")

            self._log(f"[FFmpeg] Extracted {total_frames} frames successfully.")
            report(15, f"Extracted {total_frames} frames. Beginning AI processing...")

            exe = get_engine_exe(task.model_type)
            if not exe:
                raise RuntimeError(f"Engine {task.model_type} executable not found in bin/")

            cpu_threads = "2:2:2"

            if task.model_type == "realesrgan":
                cmd = [
                    str(exe),
                    "-i", str(frames_in_dir),
                    "-o", str(frames_out_dir),
                    "-s", str(task.scale),
                    "-n", task.model_name,
                    "-m", str(exe.parent / "models"),
                    "-j", cpu_threads,
                    "-f", "png",
                    "-g", "0",
                    "-v",
                ]
            elif task.model_type == "realcugan":
                cmd = [
                    str(exe),
                    "-i", str(frames_in_dir),
                    "-o", str(frames_out_dir),
                    "-s", str(task.scale),
                    "-n", str(task.denoise),
                    "-m", str(exe.parent / "models-se"),
                    "-j", cpu_threads,
                    "-f", "png",
                    "-g", "0",
                    "-v",
                ]
            elif task.model_type == "rife":
                cmd = [
                    str(exe),
                    "-i", str(frames_in_dir),
                    "-o", str(frames_out_dir),
                    "-m", str(exe.parent / (task.model_name or "rife-v4")),
                    "-j", cpu_threads,
                    "-g", "0",
                    "-v",
                ]
            else:
                raise ValueError(f"Unknown model type: {task.model_type}")

            self._log(f"[Engine] Starting batch processing for {total_frames} frames...")
            self._log(f"[Command] {' '.join(cmd)}")

            self._current_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                cwd=str(exe.parent),
                creationflags=WIN_NO_WINDOW,
                bufsize=1,
            )

            expected_out_frames = total_frames * 2 if task.model_type == "rife" else total_frames
            start_time = time.time()

            q_vid: queue.Queue = queue.Queue()
            def vid_reader():
                try:
                    for line in iter(self._current_proc.stdout.readline, ''):
                        q_vid.put(line)
                except Exception:
                    pass
                finally:
                    try:
                        self._current_proc.stdout.close()
                    except Exception:
                        pass

            t_vid = threading.Thread(target=vid_reader, daemon=True)
            t_vid.start()

            last_progress_check = 0.0
            while self._current_proc.poll() is None or not q_vid.empty():
                if self._is_cancelled:
                    try:
                        self._current_proc.kill()
                    except Exception:
                        pass
                    raise RuntimeError("Cancelled by user.")

                try:
                    while True:
                        line = q_vid.get_nowait()
                        line_clean = line.strip()
                        if line_clean:
                            self._log(f"[{task.model_type}] {line_clean}")
                except queue.Empty:
                    pass

                now = time.time()
                if now - last_progress_check >= 0.4:
                    last_progress_check = now
                    done_count = len(list(frames_out_dir.glob("*.png")))
                    pct = 15 + int((done_count / max(1, expected_out_frames)) * 70)
                    pct = min(85, max(15, pct))

                    elapsed = now - start_time
                    if done_count > 0:
                        fps_proc = done_count / max(0.01, elapsed)
                        remaining_secs = (expected_out_frames - done_count) / max(0.01, fps_proc)
                        mins, secs = divmod(int(remaining_secs), 60)
                        eta_str = f"ETA: {mins:02d}:{secs:02d} ({fps_proc:.1f} fps)"
                    else:
                        eta_str = "Calculating ETA..."

                    report(pct, f"Processing frame {done_count}/{expected_out_frames} ({eta_str})")
                time.sleep(0.05)

            if self._is_cancelled:
                raise RuntimeError("Cancelled by user.")

            if self._current_proc.returncode != 0:
                raise RuntimeError(f"Engine processing failed with exit code {self._current_proc.returncode}")

            encoder_info = get_best_video_encoder()
            self._log(f"[FFmpeg] Assembling output video using {encoder_info['name']}...")
            report(87, f"Encoding video ({encoder_info['name']})...")
            fps = info.get("fps", 30.0)
            out_fps = fps * 2 if task.model_type == "rife" else fps

            base_encode_cmd = [
                ffmpeg, "-y",
                "-r", str(out_fps),
                "-i", str(frames_out_dir / "%08d.png"),
            ]

            if has_audio and audio_file.exists() and audio_file.stat().st_size > 0:
                base_encode_cmd.extend(["-i", str(audio_file)])
                base_encode_cmd.extend(["-c:a", "aac", "-b:a", "256k"])

            encode_cmd = list(base_encode_cmd) + encoder_info["args"] + [str(out_path)]
            self._current_proc = subprocess.Popen(
                encode_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                creationflags=WIN_NO_WINDOW,
            )
            _, encode_err = self._current_proc.communicate()

            # Fallback to libx264 if hardware encoder fails
            if (self._current_proc.returncode != 0 or not out_path.exists()) and encoder_info.get("is_hw", False):
                self._log("[FFmpeg] Hardware encoder failed, falling back to CPU (libx264)...")
                report(90, "Fallback to CPU encoder (libx264)...")
                fallback_cmd = list(base_encode_cmd) + [
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-crf", "17",
                    "-preset", "medium",
                    "-threads", "0",
                    str(out_path),
                ]
                self._current_proc = subprocess.Popen(
                    fallback_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=WIN_NO_WINDOW,
                )
                self._current_proc.wait()

            if self._is_cancelled:
                if out_path.exists():
                    out_path.unlink()
                raise RuntimeError("Cancelled by user.")

            if not out_path.exists():
                raise RuntimeError("Final video assembly failed.")

            self._log(f"[Complete] Final video saved: {out_path.name}")
            report(100, "Done!")
            return out_path
        finally:
            if self._temp_dir:
                clean_dir(self._temp_dir)
                self._temp_dir = None


class UpscaleWorker(QThread):
    """
    Convenience single-item worker maintaining backward compatibility.
    """
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str, str)
    log_message = pyqtSignal(str)

    def __init__(
        self,
        input_path: str,
        output_dir: str,
        model_type: str,
        model_name: str,
        scale: int = 4,
        denoise: int = 0,
        custom_out_name: Optional[str] = None,
    ):
        super().__init__()
        self.task = QueueTask(
            task_id="single",
            input_path=Path(input_path).resolve(),
            output_dir=Path(output_dir).resolve(),
            model_type=model_type,
            model_name=model_name,
            scale=scale,
            denoise=denoise,
            custom_out_name=custom_out_name,
        )
        self._batch_worker = BatchUpscaleWorker([self.task])
        self._batch_worker.item_progress.connect(lambda idx, pct, msg: self.progress.emit(pct, msg))
        self._batch_worker.item_finished.connect(lambda idx, succ, path, msg: self.finished.emit(succ, path, msg))
        self._batch_worker.log_message.connect(self.log_message.emit)

    def cancel(self):
        self._batch_worker.cancel()

    def run(self):
        self._batch_worker.run()

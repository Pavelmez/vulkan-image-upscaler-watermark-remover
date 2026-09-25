import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable

import cv2
import numpy as np
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
BIN_DIR = BASE_DIR / "bin"
INPAINT_DIR = BIN_DIR / "inpainting"

INPAINTING_MODELS: Dict[str, Dict[str, Any]] = {
    "big-lama": {
        "name": "Big-LaMa (General / Text & Watermarks)",
        "tag": "big-lama",
        "file": "lama_fp32.onnx",
        "url": "https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx",
        "size_mb": 198,
        "type": "lama",
        "description": "Gold standard Fast Fourier Convolution (FFC) model. Unmatched accuracy for photos, text, watermarks, timestamps, and general object removal.",
    },
    "manga-lama": {
        "name": "Manga-LaMa (Anime & Manga Text / Bubbles)",
        "tag": "manga-lama",
        "file": "lama-manga-dynamic.onnx",
        "url": "https://huggingface.co/QuatZo/tara-models/resolve/main/lama-manga-dynamic.onnx",
        "size_mb": 197,
        "type": "lama",
        "description": "Fine-tuned specifically on manga, comics, and anime illustrations. Replaces speech bubbles and text while restoring screentones and line art.",
    },
    "aot": {
        "name": "AOT-Inpainting (Fast Contextual / Large Objects)",
        "tag": "aot",
        "file": "aot.onnx",
        "url": "https://huggingface.co/ogkalu/aot-inpainting/resolve/main/aot.onnx",
        "size_mb": 22,
        "type": "aot",
        "description": "Aggregated Contextual Transformations. Ultra-lightweight (~22MB) and fast, great for removing large objects with continuous context.",
    },
    "opencv-telea": {
        "name": "Fast PatchMatch (Instant / Built-in)",
        "tag": "opencv-telea",
        "file": None,
        "url": None,
        "size_mb": 0,
        "type": "opencv",
        "description": "Fast Marching Method (Telea). Built-in with zero download required. Runs in ~15ms, good for quick small touch-ups.",
    },
}


def get_model_file_path(model_key: str) -> Optional[Path]:
    """Get absolute path to model file if it uses one."""
    meta = INPAINTING_MODELS.get(model_key)
    if not meta or not meta["file"]:
        return None
    return INPAINT_DIR / meta["file"]


def is_inpainting_installed(model_key: str) -> bool:
    """Check if model is ready to use."""
    meta = INPAINTING_MODELS.get(model_key)
    if not meta:
        return False
    if meta["type"] == "opencv":
        return True
    path = get_model_file_path(model_key)
    if not path or not path.is_file():
        return False
    expected_bytes = int(meta.get("size_mb", 1) * 0.8 * 1024 * 1024)
    return path.stat().st_size >= expected_bytes


def check_all_inpainting_installed() -> Dict[str, bool]:
    """Check installation status for all inpainting models."""
    return {k: is_inpainting_installed(k) for k in INPAINTING_MODELS}


def download_inpainting_model(
    model_key: str,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> bool:
    """Download specified inpainting ONNX model with real-time progress and resume support."""
    meta = INPAINTING_MODELS.get(model_key)
    if not meta or not meta["url"]:
        return True

    INPAINT_DIR.mkdir(parents=True, exist_ok=True)
    target_path = INPAINT_DIR / meta["file"]
    temp_path = INPAINT_DIR / f"{meta['file']}.part"

    if is_inpainting_installed(model_key):
        return True

    url = meta["url"]
    name = meta["name"]
    max_retries = 5

    for attempt in range(max_retries):
        try:
            downloaded = temp_path.stat().st_size if temp_path.exists() else 0
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"

            if progress_callback:
                progress_callback(f"Connecting to {name}...", downloaded, 100)

            resp = requests.get(url, stream=True, headers=headers, timeout=30)
            if resp.status_code not in (200, 206):
                resp.raise_for_status()

            total_size = downloaded
            if "content-range" in resp.headers:
                cr = resp.headers["content-range"]
                total_size = int(cr.split("/")[-1])
            elif "content-length" in resp.headers:
                total_size = downloaded + int(resp.headers["content-length"])

            mode = "ab" if downloaded > 0 else "wb"
            with open(temp_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=262144):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        mb_done = downloaded / (1024 * 1024)
                        mb_tot = total_size / (1024 * 1024)
                        progress_callback(f"Downloading {name} ({mb_done:.1f}MB / {mb_tot:.1f}MB)...", downloaded, total_size)

            if total_size > 0 and downloaded >= int(total_size * 0.99):
                if target_path.exists():
                    target_path.unlink()
                temp_path.rename(target_path)
                if progress_callback:
                    progress_callback(f"{name} ready!", total_size, total_size)
                return True
        except Exception:
            if attempt == max_retries - 1:
                raise
            time.sleep(1 + attempt * 2)

    return False


class InpainterEngine:
    """
    High-performance inpainting engine supporting Big-LaMa, Manga-LaMa, AOT, and OpenCV.
    Caches ONNX sessions for fast interactive editing.
    """
    def __init__(self):
        self._sessions = {}

    def _get_session(self, model_key: str):
        if model_key not in self._sessions:
            model_path = get_model_file_path(model_key)
            if not model_path or not model_path.exists():
                raise FileNotFoundError(f"Model file not found for {model_key}: {model_path}")

            import onnxruntime as ort
            available = ort.get_available_providers()
            providers = []
            if "DmlExecutionProvider" in available:
                providers.append("DmlExecutionProvider")
            if "CPUExecutionProvider" in available:
                providers.append("CPUExecutionProvider")

            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._sessions[model_key] = ort.InferenceSession(str(model_path), sess_options=sess_options, providers=providers)

        return self._sessions[model_key]

    def _inpaint_tensor_lama(self, session, img_bgr_patch: np.ndarray, mask_patch: np.ndarray, model_key: str) -> np.ndarray:
        """Run single inference forward pass of LaMa model."""
        rgb = cv2.cvtColor(img_bgr_patch, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img_tensor = np.transpose(rgb, (2, 0, 1))[np.newaxis, ...]
        mask_tensor = (mask_patch.astype(np.float32) / 255.0)[np.newaxis, np.newaxis, ...]
        mask_tensor = (mask_tensor > 0.5).astype(np.float32)

        input_names = [inp.name for inp in session.get_inputs()]
        feed = {}
        if "image" in input_names:
            feed["image"] = img_tensor
        elif "input_image" in input_names:
            feed["input_image"] = img_tensor
        else:
            feed[input_names[0]] = img_tensor

        if "mask" in input_names:
            feed["mask"] = mask_tensor
        elif "input_mask" in input_names:
            feed["input_mask"] = mask_tensor
        else:
            feed[input_names[1]] = mask_tensor

        out_tensor = session.run(None, feed)[0]
        if out_tensor.ndim == 4:
            out_tensor = out_tensor[0]
        out_img = np.transpose(out_tensor, (1, 2, 0))

        if "manga" in model_key:
            out_img = np.clip(out_img * 255.0, 0, 255).astype(np.uint8)
        else:
            if out_img.max() <= 1.5:
                out_img = out_img * 255.0
            out_img = np.clip(out_img, 0, 255).astype(np.uint8)

        return cv2.cvtColor(out_img, cv2.COLOR_RGB2BGR)

    def _inpaint_tensor_aot(self, session, img_bgr_patch: np.ndarray, mask_patch: np.ndarray) -> np.ndarray:
        """Run single inference forward pass of AOT model."""
        rgb = cv2.cvtColor(img_bgr_patch, cv2.COLOR_BGR2RGB).astype(np.float32)
        img_norm = (rgb / 127.5) - 1.0
        bin_mask = mask_patch > 128
        img_norm[bin_mask] = 0.0

        img_tensor = np.transpose(img_norm, (2, 0, 1))[np.newaxis, ...]
        mask_tensor = bin_mask.astype(np.float32)[np.newaxis, np.newaxis, ...]

        input_names = [inp.name for inp in session.get_inputs()]
        feed = {
            input_names[0]: img_tensor,
            input_names[1]: mask_tensor,
        }

        out_tensor = session.run(None, feed)[0]
        if out_tensor.ndim == 4:
            out_tensor = out_tensor[0]
        out_img = np.transpose(out_tensor, (1, 2, 0))
        out_img = (out_img + 1.0) * 127.5
        out_img = np.clip(out_img, 0, 255).astype(np.uint8)
        return cv2.cvtColor(out_img, cv2.COLOR_RGB2BGR)

    def inpaint(self, image_bgr: np.ndarray, mask: np.ndarray, model_key: str = "big-lama") -> np.ndarray:
        """
        Execute inpainting on an image using the selected model.
        Supports both full-resolution dynamic models (AOT, Manga-LaMa)
        and fixed-resolution models (Big-LaMa 512x512) via smart contextual cropping.
        """
        meta = INPAINTING_MODELS.get(model_key)
        if not meta:
            raise ValueError(f"Unknown inpainting model: {model_key}")

        if not np.any(mask > 0):
            return image_bgr.copy()

        h, w = image_bgr.shape[:2]
        bin_mask = (mask > 0).astype(np.uint8) * 255

        if meta["type"] == "opencv":
            return cv2.inpaint(image_bgr, bin_mask, inpaintRadius=4, flags=cv2.INPAINT_TELEA)

        session = self._get_session(model_key)
        inp_shape = session.get_inputs()[0].shape

        fixed_h = inp_shape[2] if len(inp_shape) > 2 else None
        fixed_w = inp_shape[3] if len(inp_shape) > 3 else None
        is_fixed = isinstance(fixed_h, int) and isinstance(fixed_w, int) and fixed_h > 0 and fixed_w > 0

        ys, xs = np.where(bin_mask > 0)
        ymin, ymax = int(ys.min()), int(ys.max())
        xmin, xmax = int(xs.min()), int(xs.max())
        bw = xmax - xmin + 1
        bh = ymax - ymin + 1

        if bw < w * 0.85 and bh < h * 0.85:
            margin = max(bw, bh, 128)
            cx = (xmin + xmax) // 2
            cy = (ymin + ymax) // 2
            half = max(bw, bh) // 2 + margin // 2

            x1 = max(0, cx - half)
            x2 = min(w, cx + half)
            y1 = max(0, cy - half)
            y2 = min(h, cy + half)

            patch_img = image_bgr[y1:y2, x1:x2].copy()
            patch_mask = bin_mask[y1:y2, x1:x2].copy()

            if is_fixed:
                p_in_img = cv2.resize(patch_img, (fixed_w, fixed_h), interpolation=cv2.INTER_LINEAR)
                p_in_mask = cv2.resize(patch_mask, (fixed_w, fixed_h), interpolation=cv2.INTER_NEAREST)

                if meta["type"] == "lama":
                    out_bgr = self._inpaint_tensor_lama(session, p_in_img, p_in_mask, model_key)
                else:
                    out_bgr = self._inpaint_tensor_aot(session, p_in_img, p_in_mask)

                inpainted_patch = cv2.resize(out_bgr, (x2 - x1, y2 - y1), interpolation=cv2.INTER_CUBIC)
            else:
                ph, pw = patch_img.shape[:2]
                pad_h = (8 - ph % 8) % 8
                pad_w = (8 - pw % 8) % 8

                p_pad_img = cv2.copyMakeBorder(patch_img, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT)
                p_pad_mask = cv2.copyMakeBorder(patch_mask, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT)

                if meta["type"] == "lama":
                    out_bgr = self._inpaint_tensor_lama(session, p_pad_img, p_pad_mask, model_key)
                else:
                    out_bgr = self._inpaint_tensor_aot(session, p_pad_img, p_pad_mask)

                inpainted_patch = out_bgr[:ph, :pw]

            patch_mask_orig = bin_mask[y1:y2, x1:x2]
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            dilated_patch = cv2.dilate(patch_mask_orig, kernel, iterations=2)
            alpha = (cv2.GaussianBlur(dilated_patch, (9, 9), 2.0).astype(np.float32) / 255.0)[..., np.newaxis]

            result_bgr = image_bgr.copy()
            result_bgr[y1:y2, x1:x2] = (
                inpainted_patch.astype(np.float32) * alpha +
                result_bgr[y1:y2, x1:x2].astype(np.float32) * (1.0 - alpha)
            ).astype(np.uint8)
            return result_bgr
        else:
            if is_fixed:
                scaled_img = cv2.resize(image_bgr, (fixed_w, fixed_h), interpolation=cv2.INTER_LINEAR)
                scaled_mask = cv2.resize(bin_mask, (fixed_w, fixed_h), interpolation=cv2.INTER_NEAREST)

                if meta["type"] == "lama":
                    out_bgr = self._inpaint_tensor_lama(session, scaled_img, scaled_mask, model_key)
                else:
                    out_bgr = self._inpaint_tensor_aot(session, scaled_img, scaled_mask)

                clean_result = cv2.resize(out_bgr, (w, h), interpolation=cv2.INTER_CUBIC)
            else:
                pad_h = (8 - h % 8) % 8
                pad_w = (8 - w % 8) % 8

                padded_img = cv2.copyMakeBorder(image_bgr, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT)
                padded_mask = cv2.copyMakeBorder(bin_mask, 0, pad_h, 0, pad_w, cv2.BORDER_REFLECT)

                if meta["type"] == "lama":
                    out_bgr = self._inpaint_tensor_lama(session, padded_img, padded_mask, model_key)
                else:
                    out_bgr = self._inpaint_tensor_aot(session, padded_img, padded_mask)

                clean_result = out_bgr[:h, :w]

            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            dilated_mask = cv2.dilate(bin_mask, kernel, iterations=2)
            soft_mask = (cv2.GaussianBlur(dilated_mask, (7, 7), 2.0).astype(np.float32) / 255.0)[..., np.newaxis]

            final_bgr = (
                clean_result.astype(np.float32) * soft_mask +
                image_bgr.astype(np.float32) * (1.0 - soft_mask)
            )
            return np.clip(final_bgr, 0, 255).astype(np.uint8)

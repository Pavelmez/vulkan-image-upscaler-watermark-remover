import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple, List

import cv2
import numpy as np

from PyQt6.QtCore import Qt, QPoint, QRect, pyqtSignal, QThread
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QBrush,
    QMouseEvent, QWheelEvent
)
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSlider, QProgressBar,
    QFileDialog, QMessageBox, QFrame, QSizePolicy
)

from src.inpainter import (
    InpainterEngine, INPAINTING_MODELS, is_inpainting_installed,
    download_inpainting_model
)
from src.styles import DARK_STYLESHEET


def cv2_to_qimage(img_bgr: np.ndarray) -> QImage:
    """Convert BGR cv2 image to QImage safely with contiguous memory."""
    rgb = np.ascontiguousarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    h, w, ch = rgb.shape
    bytes_per_line = ch * w
    return QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()


class InteractiveBrushCanvas(QWidget):
    """
    Interactive image canvas with real-time mask painting,
    adjustable brush size, undo history, and before/after comparison preview.
    """
    brush_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.original_bgr: Optional[np.ndarray] = None
        self.current_bgr: Optional[np.ndarray] = None
        self.mask: Optional[np.ndarray] = None

        self._undo_masks: List[np.ndarray] = []
        self._max_undo = 20

        self.brush_radius = 24
        self._is_drawing = False
        self._mouse_pos: Optional[QPoint] = None
        self._last_img_point: Optional[QPoint] = None
        self._show_original = False

    def load_image(self, img_bgr_or_path):
        if isinstance(img_bgr_or_path, (str, Path)):
            img = cv2.imdecode(np.fromfile(str(img_bgr_or_path), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"Failed to read image from {img_bgr_or_path}")
            self.original_bgr = img
        else:
            self.original_bgr = img_bgr_or_path.copy()

        self.current_bgr = self.original_bgr.copy()
        h, w = self.original_bgr.shape[:2]
        self.mask = np.zeros((h, w), dtype=np.uint8)
        self._undo_masks.clear()
        self.update()

    def set_erased_result(self, result_bgr: np.ndarray):
        """Update current displayed image with the inpainting output and clear mask."""
        self.current_bgr = result_bgr.copy()
        if self.mask is not None:
            self._save_undo_state()
            self.mask.fill(0)
        self.update()

    def set_show_original(self, show: bool):
        self._show_original = show
        self.update()

    def clear_mask(self):
        if self.mask is not None and np.any(self.mask > 0):
            self._save_undo_state()
            self.mask.fill(0)
            self.update()

    def undo_mask(self):
        if self._undo_masks and self.mask is not None:
            self.mask = self._undo_masks.pop()
            self.update()

    def _save_undo_state(self):
        if self.mask is not None:
            if len(self._undo_masks) >= self._max_undo:
                self._undo_masks.pop(0)
            self._undo_masks.append(self.mask.copy())

    def set_brush_radius(self, radius: int):
        self.brush_radius = max(2, min(120, radius))
        self.brush_changed.emit(self.brush_radius)
        self.update()

    def _get_target_rect(self) -> QRect:
        if self.original_bgr is None:
            return QRect()
        h, w = self.original_bgr.shape[:2]
        vw, vh = self.width(), self.height()
        if vw <= 0 or vh <= 0 or w <= 0 or h <= 0:
            return QRect()
        scale = min(vw / w, vh / h)
        dw = int(w * scale)
        dh = int(h * scale)
        x = (vw - dw) // 2
        y = (vh - dh) // 2
        return QRect(x, y, dw, dh)

    def _widget_to_image_coords(self, pos: QPoint) -> Optional[Tuple[int, int]]:
        if self.original_bgr is None:
            return None
        rect = self._get_target_rect()
        if not rect.contains(pos):
            return None
        h, w = self.original_bgr.shape[:2]
        rx = (pos.x() - rect.x()) / rect.width()
        ry = (pos.y() - rect.y()) / rect.height()
        ix = int(rx * w)
        iy = int(ry * h)
        return (max(0, min(w - 1, ix)), max(0, min(h - 1, iy)))

    def _get_image_brush_radius(self) -> int:
        if self.original_bgr is None:
            return self.brush_radius
        rect = self._get_target_rect()
        if rect.width() <= 0:
            return self.brush_radius
        w = self.original_bgr.shape[1]
        scale = rect.width() / w
        return max(1, int(round(self.brush_radius / scale)))

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.original_bgr is not None:
            coords = self._widget_to_image_coords(event.pos())
            if coords:
                self._save_undo_state()
                self._is_drawing = True
                self._last_img_point = QPoint(coords[0], coords[1])
                r = self._get_image_brush_radius()
                cv2.circle(self.mask, coords, r, 255, -1)
                self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        self._mouse_pos = event.pos()
        if self._is_drawing and self.mask is not None:
            coords = self._widget_to_image_coords(event.pos())
            if coords and self._last_img_point:
                curr_pt = QPoint(coords[0], coords[1])
                img_r = self._get_image_brush_radius()
                cv2.line(
                    self.mask,
                    (self._last_img_point.x(), self._last_img_point.y()),
                    (curr_pt.x(), curr_pt.y()),
                    255,
                    img_r * 2,
                )
                cv2.circle(self.mask, (curr_pt.x(), curr_pt.y()), img_r, 255, -1)
                self._last_img_point = curr_pt
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_drawing = False
            self._last_img_point = None
            self.update()

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        step = 4 if abs(delta) >= 120 else 2
        new_r = self.brush_radius + (step if delta > 0 else -step)
        self.set_brush_radius(new_r)
        event.accept()

    def leaveEvent(self, event):
        self._mouse_pos = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        if self.original_bgr is None:
            painter.setPen(QColor("#475569"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No image loaded. Drop or select an image to begin.")
            return

        rect = self._get_target_rect()
        if rect.isEmpty():
            return

        active_bgr = self.original_bgr if self._show_original else self.current_bgr
        qimg = cv2_to_qimage(active_bgr)
        painter.drawImage(rect, qimg)

        # Draw red translucent mask overlay
        if self.mask is not None and not self._show_original and np.any(self.mask > 0):
            disp_w = rect.width()
            disp_h = rect.height()
            small_mask = cv2.resize(self.mask, (disp_w, disp_h), interpolation=cv2.INTER_NEAREST)

            rgba = np.zeros((disp_h, disp_w, 4), dtype=np.uint8)
            mask_bool = small_mask > 0
            rgba[mask_bool] = [239, 68, 68, 160]

            mask_qimg = QImage(rgba.data, disp_w, disp_h, disp_w * 4, QImage.Format.Format_RGBA8888).copy()
            painter.drawImage(rect, mask_qimg)

        # Draw brush cursor outline
        if self._mouse_pos and self.rect().contains(self._mouse_pos):
            painter.setPen(QPen(QColor(255, 255, 255, 230), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(239, 68, 68, 50)))
            painter.drawEllipse(self._mouse_pos, self.brush_radius, self.brush_radius)


class InpaintWorkerThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, object, str, float)

    def __init__(self, engine: InpainterEngine, image_bgr: np.ndarray, mask: np.ndarray, model_key: str):
        super().__init__()
        self.engine = engine
        self.image_bgr = image_bgr
        self.mask = mask
        self.model_key = model_key

    def run(self):
        t0 = time.time()
        try:
            m_name = INPAINTING_MODELS.get(self.model_key, {}).get("name", self.model_key)
            self.progress.emit(f"Running {m_name}...")
            res_bgr = self.engine.inpaint(self.image_bgr, self.mask, self.model_key)
            elapsed = time.time() - t0
            self.finished.emit(True, res_bgr, f"Erased successfully with {m_name} in {elapsed:.2f}s", elapsed)
        except Exception as e:
            elapsed = time.time() - t0
            self.finished.emit(False, None, str(e), elapsed)


class InpaintModelDownloadWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, model_key: str):
        super().__init__()
        self.model_key = model_key

    def run(self):
        try:
            def on_prog(msg, cur, tot):
                self.progress.emit(msg, cur, tot)

            success = download_inpainting_model(self.model_key, on_prog)
            name = INPAINTING_MODELS[self.model_key]["name"]
            if success:
                self.finished.emit(True, f"{name} installed successfully!")
            else:
                self.finished.emit(False, f"Verification failed for {name}")
        except Exception as e:
            self.finished.emit(False, str(e))


class ObjectEraserDialog(QDialog):
    send_to_queue_requested = pyqtSignal(str)

    def __init__(self, initial_image_path: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Object & Watermark Eraser")
        self.setMinimumSize(960, 680)
        self.resize(1080, 740)
        self.setStyleSheet(DARK_STYLESHEET)

        self.engine = InpainterEngine()
        self.worker: Optional[InpaintWorkerThread] = None
        self.dl_worker: Optional[InpaintModelDownloadWorker] = None
        self.current_filepath: Optional[str] = initial_image_path

        self._build_ui()

        if self.current_filepath and os.path.exists(self.current_filepath):
            self.canvas.load_image(self.current_filepath)
            self.file_lbl.setText(f"File: {Path(self.current_filepath).name}")

        self._on_model_changed()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        # Top Bar
        top_bar = QFrame()
        top_bar.setObjectName("Card")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(12)

        title_vbox = QVBoxLayout()
        title_vbox.setSpacing(2)
        title = QLabel("Object & Watermark Eraser")
        title.setObjectName("HeaderTitle")
        title_vbox.addWidget(title)

        self.file_lbl = QLabel("No image loaded")
        self.file_lbl.setObjectName("SubtitleLabel")
        title_vbox.addWidget(self.file_lbl)
        top_layout.addLayout(title_vbox)

        top_layout.addStretch()

        open_btn = QPushButton("Open Image...")
        open_btn.setObjectName("SecondaryButton")
        open_btn.clicked.connect(self._open_image)
        top_layout.addWidget(open_btn)

        top_layout.addSpacing(10)
        top_layout.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setFixedHeight(30)
        for key, info in INPAINTING_MODELS.items():
            self.model_combo.addItem(info["name"], key)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        top_layout.addWidget(self.model_combo)

        self.model_badge = QLabel("Installed")
        self.model_badge.setObjectName("BadgeSuccess")
        top_layout.addWidget(self.model_badge)

        self.download_btn = QPushButton("Download")
        self.download_btn.setObjectName("PrimaryButton")
        self.download_btn.setFixedHeight(28)
        self.download_btn.setVisible(False)
        self.download_btn.clicked.connect(self._download_selected_model)
        top_layout.addWidget(self.download_btn)

        layout.addWidget(top_bar)

        # Center Canvas
        self.canvas = InteractiveBrushCanvas(self)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.brush_changed.connect(lambda r: self.brush_slider.setValue(r))
        layout.addWidget(self.canvas, stretch=1)

        # Bottom Controls
        bottom_bar = QFrame()
        bottom_bar.setObjectName("BottomBar")
        bot_layout = QHBoxLayout(bottom_bar)
        bot_layout.setContentsMargins(14, 8, 14, 8)
        bot_layout.setSpacing(8)

        # Brush Controls Group
        brush_box = QHBoxLayout()
        brush_box.setSpacing(6)
        brush_lbl = QLabel("Brush:")
        brush_lbl.setObjectName("SubtitleLabel")
        brush_box.addWidget(brush_lbl)

        self.brush_slider = QSlider(Qt.Orientation.Horizontal)
        self.brush_slider.setRange(2, 120)
        self.brush_slider.setValue(self.canvas.brush_radius)
        self.brush_slider.setFixedWidth(100)
        self.brush_slider.valueChanged.connect(self._on_brush_slider_changed)
        brush_box.addWidget(self.brush_slider)

        self.brush_size_lbl = QLabel(f"{self.canvas.brush_radius}px")
        self.brush_size_lbl.setFixedWidth(40)
        self.brush_size_lbl.setStyleSheet("color: #818cf8; font-weight: 600; font-size: 12px;")
        brush_box.addWidget(self.brush_size_lbl)
        bot_layout.addLayout(brush_box)

        bot_layout.addSpacing(6)

        # Undo & Clear & Compare
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.setObjectName("SecondaryButton")
        self.undo_btn.setFixedHeight(30)
        self.undo_btn.clicked.connect(self.canvas.undo_mask)
        bot_layout.addWidget(self.undo_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.setToolTip("Clear drawn mask")
        self.clear_btn.clicked.connect(self.canvas.clear_mask)
        bot_layout.addWidget(self.clear_btn)

        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setObjectName("SecondaryButton")
        self.compare_btn.setFixedHeight(30)
        self.compare_btn.setToolTip("Hold to preview original image")
        self.compare_btn.pressed.connect(lambda: self.canvas.set_show_original(True))
        self.compare_btn.released.connect(lambda: self.canvas.set_show_original(False))
        bot_layout.addWidget(self.compare_btn)

        bot_layout.addStretch()

        # Action Buttons
        save_btn = QPushButton("Save...")
        save_btn.setObjectName("SecondaryButton")
        save_btn.setFixedHeight(32)
        save_btn.clicked.connect(self._save_image)
        bot_layout.addWidget(save_btn)

        self.send_btn = QPushButton("Send to Upscaler")
        self.send_btn.setObjectName("SecondaryButton")
        self.send_btn.setFixedHeight(32)
        self.send_btn.clicked.connect(self._send_to_upscaler)
        bot_layout.addWidget(self.send_btn)

        self.erase_btn = QPushButton("Erase")
        self.erase_btn.setObjectName("PrimaryButton")
        self.erase_btn.setFixedHeight(32)
        self.erase_btn.setMinimumWidth(80)
        self.erase_btn.clicked.connect(self._start_erase)
        bot_layout.addWidget(self.erase_btn)

        layout.addWidget(bottom_bar)

        # Progress row
        status_row = QHBoxLayout()
        self.status_lbl = QLabel("Ready")
        self.status_lbl.setObjectName("SubtitleLabel")
        status_row.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedWidth(200)
        status_row.addWidget(self.progress_bar)

        layout.addLayout(status_row)

    def _on_model_changed(self):
        model_key = self.model_combo.currentData()
        if not model_key:
            return
        installed = is_inpainting_installed(model_key)
        if installed:
            self.model_badge.setText("Ready")
            self.model_badge.setObjectName("BadgeSuccess")
            self.download_btn.setVisible(False)
        else:
            self.model_badge.setText("Not Installed")
            self.model_badge.setObjectName("BadgeReady")
            self.download_btn.setVisible(True)

        self.model_badge.style().unpolish(self.model_badge)
        self.model_badge.style().polish(self.model_badge)

    def _on_brush_slider_changed(self, val: int):
        self.canvas.set_brush_radius(val)
        self.brush_size_lbl.setText(f"{val}px")

    def _open_image(self):
        file_filter = "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*.*)"
        path, _ = QFileDialog.getOpenFileName(self, "Open Image to Erase", "", file_filter)
        if path:
            self.current_filepath = path
            self.canvas.load_image(path)
            self.file_lbl.setText(f"File: {Path(path).name}")

    def _download_selected_model(self):
        model_key = self.model_combo.currentData()
        if not model_key:
            return
        self.download_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.dl_worker = InpaintModelDownloadWorker(model_key)
        self.dl_worker.progress.connect(self._on_dl_progress)
        self.dl_worker.finished.connect(self._on_dl_finished)
        self.dl_worker.start()

    def _on_dl_progress(self, msg: str, cur: int, tot: int):
        self.status_lbl.setText(msg)
        if tot > 0:
            self.progress_bar.setValue(int((cur / tot) * 100))

    def _on_dl_finished(self, success: bool, msg: str):
        self.download_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_lbl.setText(msg)
        self._on_model_changed()

    def _start_erase(self):
        if self.canvas.original_bgr is None:
            QMessageBox.warning(self, "No Image", "Please load an image first.")
            return

        if self.canvas.mask is None or not np.any(self.canvas.mask > 0):
            QMessageBox.information(self, "No Mask", "Please brush over the object or watermark you want to erase first.")
            return

        model_key = self.model_combo.currentData()
        if not is_inpainting_installed(model_key):
            resp = QMessageBox.question(
                self,
                "Model Not Downloaded",
                f"The model '{model_key}' needs to be downloaded first.\nDownload it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if resp == QMessageBox.StandardButton.Yes:
                self._download_selected_model()
            return

        self.erase_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_lbl.setText("Erasing object with neural inpainting...")

        self.worker = InpaintWorkerThread(
            engine=self.engine,
            image_bgr=self.canvas.current_bgr,
            mask=self.canvas.mask,
            model_key=model_key
        )
        self.worker.progress.connect(lambda msg: self.status_lbl.setText(msg))
        self.worker.finished.connect(self._on_erase_finished)
        self.worker.start()

    def _on_erase_finished(self, success: bool, res_bgr: Optional[np.ndarray], msg: str, elapsed: float):
        self.erase_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)

        if success and res_bgr is not None:
            self.canvas.set_erased_result(res_bgr)
            self.status_lbl.setText(msg)
        else:
            self.status_lbl.setText(f"Error: {msg}")
            QMessageBox.critical(self, "Eraser Error", f"Inpainting failed:\n{msg}")

    def _save_image(self):
        if self.canvas.current_bgr is None:
            return

        initial = ""
        if self.current_filepath:
            p = Path(self.current_filepath)
            initial = str(p.parent / f"{p.stem}_erased.png")

        out_path, _ = QFileDialog.getSaveFileName(self, "Save Cleaned Image", initial, "PNG (*.png);;JPG (*.jpg);;All Files (*.*)")
        if out_path:
            ext = Path(out_path).suffix.lower()
            succ, buf = cv2.imencode(ext if ext else ".png", self.canvas.current_bgr)
            if succ:
                buf.tofile(out_path)
                self.status_lbl.setText(f"Saved: {Path(out_path).name}")

    def _send_to_upscaler(self):
        if self.canvas.current_bgr is None:
            return

        stem = Path(self.current_filepath).stem if self.current_filepath else "erased_image"
        out_dir = Path(__file__).resolve().parent.parent / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{stem}_cleaned_{int(time.time())}.png"

        succ, buf = cv2.imencode(".png", self.canvas.current_bgr)
        if succ:
            buf.tofile(str(out_file))
            self.send_to_queue_requested.emit(str(out_file))
            self.accept()

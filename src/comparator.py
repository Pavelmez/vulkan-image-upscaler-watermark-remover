import os
from pathlib import Path
from typing import Optional, List, Tuple

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QBrush, QFont, QWheelEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QFileDialog, QFrame, QButtonGroup
)

from src.utils import is_image_file, format_size
from src.styles import DARK_STYLESHEET


class SplitSliderCanvas(QWidget):
    """
    Interactive canvas displaying two images with a draggable vertical split slider.
    Both images are aligned so the user can wipe between Image A and Image B.
    Supports mouse-wheel zoom and middle/left-click drag when zoomed.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        self.pixmap_a: Optional[QPixmap] = None
        self.pixmap_b: Optional[QPixmap] = None
        self.path_a: Optional[str] = None
        self.path_b: Optional[str] = None

        self.split_pos: float = 0.5  # 0.0 to 1.0 (horizontal fraction)
        self.is_dragging_split: bool = False
        self.is_panning: bool = False
        self.last_mouse_pos = QPoint()

        self.zoom: float = 1.0  # 1.0 = fit to view
        self.pan_offset = QPoint(0, 0)

    def load_images(self, path_a: Optional[str], path_b: Optional[str]):
        self.path_a = path_a
        self.path_b = path_b

        if path_a and os.path.exists(path_a):
            self.pixmap_a = QPixmap(path_a)
        else:
            self.pixmap_a = None

        if path_b and os.path.exists(path_b):
            self.pixmap_b = QPixmap(path_b)
        else:
            self.pixmap_b = None

        self.reset_view()
        self.update()

    def reset_view(self):
        self.zoom = 1.0
        self.pan_offset = QPoint(0, 0)
        self.split_pos = 0.5
        self.update()

    def set_zoom(self, zoom_val: float):
        self.zoom = max(0.2, min(8.0, zoom_val))
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        split_px = int(self.width() * self.split_pos)
        if abs(event.pos().x() - split_px) <= 15:
            self.is_dragging_split = True
            self.setCursor(Qt.CursorShape.SplitHCursor)
            return

        if event.button() == Qt.MouseButton.LeftButton or event.button() == Qt.MouseButton.MiddleButton:
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        split_px = int(self.width() * self.split_pos)

        if self.is_dragging_split:
            new_pos = event.pos().x() / max(1, self.width())
            self.split_pos = max(0.02, min(0.98, new_pos))
            self.update()
        elif self.is_panning:
            delta = event.pos() - self.last_mouse_pos
            self.last_mouse_pos = event.pos()
            self.pan_offset += delta
            self.update()
        else:
            if abs(event.pos().x() - split_px) <= 10:
                self.setCursor(Qt.CursorShape.SplitHCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.is_dragging_split = False
        self.is_panning = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 0.85
        self.set_zoom(self.zoom * factor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#0d0f15"))

        w, h = self.width(), self.height()
        if not self.pixmap_a and not self.pixmap_b:
            painter.setPen(QColor("#64748b"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Select two images to compare")
            return

        # Reference geometry: use larger pixmap or available one
        ref_pix = self.pixmap_b or self.pixmap_a
        rw, rh = ref_pix.width(), ref_pix.height()

        # Compute aspect fit into viewport
        scale_fit = min((w - 40) / max(1, rw), (h - 40) / max(1, rh))
        draw_w = rw * scale_fit * self.zoom
        draw_h = rh * scale_fit * self.zoom

        center_x = (w - draw_w) / 2 + self.pan_offset.x()
        center_y = (h - draw_h) / 2 + self.pan_offset.y()
        target_rect = QRectF(center_x, center_y, draw_w, draw_h)

        split_px = int(w * self.split_pos)

        # Draw Left: Image A
        if self.pixmap_a:
            painter.save()
            painter.setClipRect(0, 0, split_px, h)
            painter.drawPixmap(target_rect.toRect(), self.pixmap_a)
            painter.restore()

        # Draw Right: Image B
        if self.pixmap_b:
            painter.save()
            painter.setClipRect(split_px, 0, w - split_px, h)
            painter.drawPixmap(target_rect.toRect(), self.pixmap_b)
            painter.restore()

        # Draw Divider Line
        painter.setPen(QPen(QColor("#6366f1"), 2))
        painter.drawLine(split_px, 0, split_px, h)

        # Draw Handle circle
        handle_y = h // 2
        painter.setBrush(QBrush(QColor("#4f46e5")))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawEllipse(QPoint(split_px, handle_y), 16, 16)

        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QRect(split_px - 16, handle_y - 16, 32, 32), Qt.AlignmentFlag.AlignCenter, "↔")

        # Overlay Labels (Floating badges)
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        if self.path_a:
            lbl_a = f"A: {Path(self.path_a).name}"
            painter.setBrush(QBrush(QColor(15, 23, 42, 200)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(16, 16, 220, 28, 6, 6)
            painter.setPen(QColor("#93c5fd"))
            painter.drawText(QRect(22, 16, 210, 28), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lbl_a)

        if self.path_b:
            lbl_b = f"B: {Path(self.path_b).name}"
            painter.setBrush(QBrush(QColor(15, 23, 42, 200)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(w - 236, 16, 220, 28, 6, 6)
            painter.setPen(QColor("#c084fc"))
            painter.drawText(QRect(w - 230, 16, 210, 28), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lbl_b)


class SideBySideCanvas(QWidget):
    """
    Two panels side-by-side with synchronized pan and zoom.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap_a: Optional[QPixmap] = None
        self.pixmap_b: Optional[QPixmap] = None
        self.path_a: Optional[str] = None
        self.path_b: Optional[str] = None

        self.zoom: float = 1.0
        self.pan_offset = QPoint(0, 0)
        self.is_panning: bool = False
        self.last_mouse_pos = QPoint()

    def load_images(self, path_a: Optional[str], path_b: Optional[str]):
        self.path_a = path_a
        self.path_b = path_b

        if path_a and os.path.exists(path_a):
            self.pixmap_a = QPixmap(path_a)
        else:
            self.pixmap_a = None

        if path_b and os.path.exists(path_b):
            self.pixmap_b = QPixmap(path_b)
        else:
            self.pixmap_b = None

        self.zoom = 1.0
        self.pan_offset = QPoint(0, 0)
        self.update()

    def reset_view(self):
        self.zoom = 1.0
        self.pan_offset = QPoint(0, 0)
        self.update()

    def set_zoom(self, zoom_val: float):
        self.zoom = max(0.2, min(8.0, zoom_val))
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self.is_panning = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.is_panning:
            delta = event.pos() - self.last_mouse_pos
            self.last_mouse_pos = event.pos()
            self.pan_offset += delta
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.is_panning = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        factor = 1.15 if delta > 0 else 0.85
        self.set_zoom(self.zoom * factor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#0d0f15"))

        w, h = self.width(), self.height()
        half_w = w // 2

        # Left pane: Image A
        painter.save()
        painter.setClipRect(0, 0, half_w, h)
        if self.pixmap_a:
            self._draw_image_fitted(painter, self.pixmap_a, 0, 0, half_w, h)
        else:
            painter.setPen(QColor("#64748b"))
            painter.drawText(QRect(0, 0, half_w, h), Qt.AlignmentFlag.AlignCenter, "No Image A Selected")
        painter.restore()

        # Right pane: Image B
        painter.save()
        painter.setClipRect(half_w, 0, w - half_w, h)
        if self.pixmap_b:
            self._draw_image_fitted(painter, self.pixmap_b, half_w, 0, w - half_w, h)
        else:
            painter.setPen(QColor("#64748b"))
            painter.drawText(QRect(half_w, 0, w - half_w, h), Qt.AlignmentFlag.AlignCenter, "No Image B Selected")
        painter.restore()

        # Divider line
        painter.setPen(QPen(QColor("#2d3345"), 2))
        painter.drawLine(half_w, 0, half_w, h)

        # Labels
        painter.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        if self.path_a:
            painter.setBrush(QBrush(QColor(15, 23, 42, 200)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(16, 16, 220, 28, 6, 6)
            painter.setPen(QColor("#93c5fd"))
            painter.drawText(QRect(22, 16, 210, 28), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"A: {Path(self.path_a).name}")

        if self.path_b:
            painter.setBrush(QBrush(QColor(15, 23, 42, 200)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(half_w + 16, 16, 220, 28, 6, 6)
            painter.setPen(QColor("#c084fc"))
            painter.drawText(QRect(half_w + 22, 16, 210, 28), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"B: {Path(self.path_b).name}")

    def _draw_image_fitted(self, painter: QPainter, pixmap: QPixmap, vx, vy, vw, vh):
        scale_fit = min((vw - 30) / max(1, pixmap.width()), (vh - 30) / max(1, pixmap.height()))
        draw_w = pixmap.width() * scale_fit * self.zoom
        draw_h = pixmap.height() * scale_fit * self.zoom

        center_x = vx + (vw - draw_w) / 2 + self.pan_offset.x()
        center_y = vy + (vh - draw_h) / 2 + self.pan_offset.y()
        target_rect = QRectF(center_x, center_y, draw_w, draw_h)
        painter.drawPixmap(target_rect.toRect(), pixmap)


class ImageComparatorDialog(QDialog):
    """
    Dialog allowing visual comparison between two images (e.g. Original vs Upscaled,
    or Model A output vs Model B output).
    """
    def __init__(self, recent_files: Optional[List[str]] = None, initial_a: Optional[str] = None, initial_b: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Comparator - Model Output Comparison")
        self.resize(1080, 760)
        self.setMinimumSize(850, 600)
        self.setStyleSheet(DARK_STYLESHEET)

        self.recent_files = [f for f in (recent_files or []) if is_image_file(f) and os.path.exists(f)]
        self.path_a: Optional[str] = initial_a if (initial_a and os.path.exists(initial_a)) else (self.recent_files[0] if self.recent_files else None)
        self.path_b: Optional[str] = initial_b if (initial_b and os.path.exists(initial_b)) else (self.recent_files[1] if len(self.recent_files) > 1 else None)

        self._build_ui()
        self._update_canvases()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Top Bar: File selectors & Mode switch
        top_bar = QFrame()
        top_bar.setObjectName("Card")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(16)

        # Image A Selector
        a_box = QHBoxLayout()
        a_lbl = QLabel("Image A:")
        a_lbl.setStyleSheet("font-weight: 600; color: #93c5fd;")
        a_box.addWidget(a_lbl)

        self.combo_a = QComboBox()
        self.combo_a.setMinimumWidth(220)
        self.combo_a.setFixedHeight(32)
        self._populate_combo(self.combo_a, self.path_a)
        self.combo_a.currentIndexChanged.connect(self._on_combo_a_changed)
        a_box.addWidget(self.combo_a)

        btn_browse_a = QPushButton("Browse...")
        btn_browse_a.setObjectName("SecondaryButton")
        btn_browse_a.clicked.connect(self._browse_a)
        a_box.addWidget(btn_browse_a)
        top_layout.addLayout(a_box)

        top_layout.addSpacing(10)

        # Image B Selector
        b_box = QHBoxLayout()
        b_lbl = QLabel("Image B:")
        b_lbl.setStyleSheet("font-weight: 600; color: #c084fc;")
        b_box.addWidget(b_lbl)

        self.combo_b = QComboBox()
        self.combo_b.setMinimumWidth(220)
        self.combo_b.setFixedHeight(32)
        self._populate_combo(self.combo_b, self.path_b)
        self.combo_b.currentIndexChanged.connect(self._on_combo_b_changed)
        b_box.addWidget(self.combo_b)

        btn_browse_b = QPushButton("Browse...")
        btn_browse_b.setObjectName("SecondaryButton")
        btn_browse_b.clicked.connect(self._browse_b)
        b_box.addWidget(btn_browse_b)
        top_layout.addLayout(b_box)

        top_layout.addStretch()

        # View Mode Toggle: Split Slider vs Side-by-Side
        self.mode_split_btn = QPushButton("Split Slider")
        self.mode_split_btn.setObjectName("PrimaryButton")
        self.mode_split_btn.setCheckable(True)
        self.mode_split_btn.setChecked(True)
        self.mode_split_btn.clicked.connect(lambda: self._set_mode("split"))
        top_layout.addWidget(self.mode_split_btn)

        self.mode_side_btn = QPushButton("Side by Side")
        self.mode_side_btn.setObjectName("SecondaryButton")
        self.mode_side_btn.setCheckable(True)
        self.mode_side_btn.clicked.connect(lambda: self._set_mode("side"))
        top_layout.addWidget(self.mode_side_btn)

        layout.addWidget(top_bar)

        # Viewport Area
        self.viewport_container = QFrame()
        self.viewport_container.setObjectName("Card")
        self.viewport_layout = QVBoxLayout(self.viewport_container)
        self.viewport_layout.setContentsMargins(4, 4, 4, 4)

        self.split_canvas = SplitSliderCanvas()
        self.side_canvas = SideBySideCanvas()
        self.side_canvas.setVisible(False)

        self.viewport_layout.addWidget(self.split_canvas)
        self.viewport_layout.addWidget(self.side_canvas)
        layout.addWidget(self.viewport_container, stretch=1)

        # Bottom Bar: Zoom controls & Image Metadata Info
        bottom_bar = QHBoxLayout()

        self.meta_label_a = QLabel("")
        self.meta_label_a.setStyleSheet("color: #93c5fd; font-size: 12px;")
        bottom_bar.addWidget(self.meta_label_a)

        bottom_bar.addStretch()

        # Zoom buttons
        zoom_in_btn = QPushButton("Zoom In (+)")
        zoom_in_btn.setObjectName("SecondaryButton")
        zoom_in_btn.clicked.connect(self._zoom_in)
        bottom_bar.addWidget(zoom_in_btn)

        zoom_out_btn = QPushButton("Zoom Out (-)")
        zoom_out_btn.setObjectName("SecondaryButton")
        zoom_out_btn.clicked.connect(self._zoom_out)
        bottom_bar.addWidget(zoom_out_btn)

        fit_btn = QPushButton("Fit to View")
        fit_btn.setObjectName("SecondaryButton")
        fit_btn.clicked.connect(self._reset_view)
        bottom_bar.addWidget(fit_btn)


        bottom_bar.addStretch()

        self.meta_label_b = QLabel("")
        self.meta_label_b.setStyleSheet("color: #c084fc; font-size: 12px;")
        bottom_bar.addWidget(self.meta_label_b)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.accept)
        bottom_bar.addWidget(close_btn)

        layout.addLayout(bottom_bar)

    def _populate_combo(self, combo: QComboBox, current_path: Optional[str]):
        combo.clear()
        if not self.recent_files and not current_path:
            combo.addItem("No images loaded", "")
            return

        added_paths = set()
        if current_path and os.path.exists(current_path):
            combo.addItem(f"{Path(current_path).name}", current_path)
            added_paths.add(current_path)

        for p in self.recent_files:
            if p not in added_paths and os.path.exists(p):
                combo.addItem(f"{Path(p).name}", p)
                added_paths.add(p)

    def _on_combo_a_changed(self):
        self.path_a = self.combo_a.currentData()
        self._update_canvases()

    def _on_combo_b_changed(self):
        self.path_b = self.combo_b.currentData()
        self._update_canvases()

    def _browse_a(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Image A", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.path_a = path
            if path not in self.recent_files:
                self.recent_files.insert(0, path)
            self._populate_combo(self.combo_a, self.path_a)
            self._update_canvases()

    def _browse_b(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Image B", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.path_b = path
            if path not in self.recent_files:
                self.recent_files.insert(0, path)
            self._populate_combo(self.combo_b, self.path_b)
            self._update_canvases()

    def _set_mode(self, mode: str):
        if mode == "split":
            self.mode_split_btn.setChecked(True)
            self.mode_side_btn.setChecked(False)
            self.split_canvas.setVisible(True)
            self.side_canvas.setVisible(False)
        else:
            self.mode_split_btn.setChecked(False)
            self.mode_side_btn.setChecked(True)
            self.split_canvas.setVisible(False)
            self.side_canvas.setVisible(True)

    def _zoom_in(self):
        if self.split_canvas.isVisible():
            self.split_canvas.set_zoom(self.split_canvas.zoom * 1.25)
        else:
            self.side_canvas.set_zoom(self.side_canvas.zoom * 1.25)

    def _zoom_out(self):
        if self.split_canvas.isVisible():
            self.split_canvas.set_zoom(self.split_canvas.zoom * 0.8)
        else:
            self.side_canvas.set_zoom(self.side_canvas.zoom * 0.8)

    def _reset_view(self):
        self.split_canvas.reset_view()
        self.side_canvas.reset_view()

    def _update_canvases(self):
        self.split_canvas.load_images(self.path_a, self.path_b)
        self.side_canvas.load_images(self.path_a, self.path_b)

        # Update metadata info
        if self.path_a and os.path.exists(self.path_a):
            pa = Path(self.path_a)
            pix_a = QPixmap(self.path_a)
            size_a = format_size(pa.stat().st_size)
            self.meta_label_a.setText(f"Image A: {pa.name} • {pix_a.width()} × {pix_a.height()} • {size_a}")
        else:
            self.meta_label_a.setText("Image A: (None)")

        if self.path_b and os.path.exists(self.path_b):
            pb = Path(self.path_b)
            pix_b = QPixmap(self.path_b)
            size_b = format_size(pb.stat().st_size)
            self.meta_label_b.setText(f"Image B: {pb.name} • {pix_b.width()} × {pix_b.height()} • {size_b}")
        else:
            self.meta_label_b.setText("Image B: (None)")

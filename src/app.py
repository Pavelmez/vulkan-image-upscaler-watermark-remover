import os
import sys
import uuid
from pathlib import Path
from typing import Optional, List, Dict

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QFileDialog, QProgressBar,
    QFrame, QMessageBox, QDialog, QScrollArea, QStackedWidget
)

from src.downloader import check_all_installed, download_and_extract_engine, ENGINES
from src.utils import get_media_info, is_image_file, is_video_file
from src.processor import (
    QueueTask, BatchUpscaleWorker, get_model_tag
)
from src.comparator import ImageComparatorDialog
from src.eraser_dialog import ObjectEraserDialog
from src.styles import DARK_STYLESHEET

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

MODEL_CAPABILITIES = {
    ("realesrgan", "realesrgan-x4plus"): {
        "name": "Real-ESRGAN Photo (4x)",
        "media_types": ["image", "video"],
        "scales": [(4, "4x")],
        "default_scale": 4,
        "supports_denoise": False,
    },
    ("realesrgan", "realesrgan-x4plus-anime"): {
        "name": "Real-ESRGAN Anime (4x)",
        "media_types": ["image", "video"],
        "scales": [(4, "4x")],
        "default_scale": 4,
        "supports_denoise": False,
    },
    ("realesrgan", "realesr-animevideov3"): {
        "name": "Real-ESRGAN Video / Fast (2x, 3x, 4x)",
        "media_types": ["image", "video"],
        "scales": [(2, "2x"), (3, "3x"), (4, "4x")],
        "default_scale": 2,
        "supports_denoise": False,
    },
    ("realcugan", "models-se"): {
        "name": "Real-CUGAN Anime (2x, 3x, 4x)",
        "media_types": ["image", "video"],
        "scales": [(2, "2x"), (3, "3x"), (4, "4x")],
        "default_scale": 2,
        "supports_denoise": True,
    },
    ("rife", "rife-v4"): {
        "name": "RIFE Video Motion (60fps)",
        "media_types": ["video"],
        "scales": [(1, "60fps (2x)")],
        "default_scale": 1,
        "supports_denoise": False,
    },
}


class ModelDownloadWorker(QThread):
    progress = pyqtSignal(str, int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, engine_key: str):
        super().__init__()
        self.engine_key = engine_key

    def run(self):
        try:
            def on_prog(msg, cur, tot):
                self.progress.emit(msg, cur, tot)

            success = download_and_extract_engine(self.engine_key, on_prog)
            if success:
                self.finished.emit(True, f"Installed {ENGINES[self.engine_key]['name']} successfully.")
            else:
                self.finished.emit(False, f"Verification failed for {self.engine_key}")
        except Exception as e:
            self.finished.emit(False, str(e))


class ModelManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Model Engines")
        self.setFixedSize(480, 360)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        title = QLabel("AI Upscaling Engines")
        title.setObjectName("HeaderTitle")
        layout.addWidget(title)

        subtitle = QLabel("Engines run locally on your Vulkan-compatible GPU.")
        subtitle.setObjectName("SubtitleLabel")
        layout.addWidget(subtitle)

        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(8)
        layout.addLayout(self.cards_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("")
        self.status_lbl.setObjectName("SubtitleLabel")
        layout.addWidget(self.status_lbl)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("Done")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self.download_worker: Optional[ModelDownloadWorker] = None
        self.refresh_list()

    def refresh_list(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        status = check_all_installed()
        for key, info in ENGINES.items():
            card = QFrame()
            card.setObjectName("Card")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)

            name_lbl = QLabel(info["name"])
            name_lbl.setStyleSheet("font-weight: 600; font-size: 13px;")
            card_layout.addWidget(name_lbl)
            card_layout.addStretch()

            is_inst = status.get(key, False)
            if is_inst:
                badge = QLabel("Installed")
                badge.setObjectName("BadgeSuccess")
                card_layout.addWidget(badge)
            else:
                dl_btn = QPushButton("Download")
                dl_btn.setObjectName("PrimaryButton")
                dl_btn.setFixedHeight(28)
                dl_btn.clicked.connect(lambda checked, k=key: self._start_download(k))
                card_layout.addWidget(dl_btn)

            self.cards_layout.addWidget(card)

    def _start_download(self, key):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_lbl.setText(f"Downloading {ENGINES[key]['name']}...")

        self.download_worker = ModelDownloadWorker(key)
        self.download_worker.progress.connect(self._on_dl_progress)
        self.download_worker.finished.connect(self._on_dl_finished)
        self.download_worker.start()

    def _on_dl_progress(self, msg, cur, tot):
        self.status_lbl.setText(msg)
        if tot > 0:
            self.progress_bar.setValue(int((cur / tot) * 100))

    def _on_dl_finished(self, success, msg):
        self.progress_bar.setVisible(False)
        self.status_lbl.setText(msg)
        self.refresh_list()


class DropZoneWidget(QFrame):
    files_dropped = pyqtSignal(list)
    browse_files_clicked = pyqtSignal()
    browse_folder_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZoneBox")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 24, 24, 24)

        self.title_label = QLabel("Drag & drop images or videos here")
        self.title_label.setObjectName("DropTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)

        self.sub_label = QLabel("Supports PNG, JPG, WEBP, BMP, MP4, MKV, MOV, AVI")
        self.sub_label.setObjectName("DropSubtitle")
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sub_label)

        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        add_files_btn = QPushButton("Add Files...")
        add_files_btn.setObjectName("SecondaryButton")
        add_files_btn.clicked.connect(self.browse_files_clicked.emit)
        btn_box.addWidget(add_files_btn)

        add_folder_btn = QPushButton("Add Folder...")
        add_folder_btn.setObjectName("SecondaryButton")
        add_folder_btn.clicked.connect(self.browse_folder_clicked.emit)
        btn_box.addWidget(add_folder_btn)

        layout.addLayout(btn_box)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setObjectName("DropZoneBoxActive")
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, event):
        self.setObjectName("DropZoneBox")
        self.style().unpolish(self)
        self.style().polish(self)
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self.setObjectName("DropZoneBox")
        self.style().unpolish(self)
        self.style().polish(self)
        urls = event.mimeData().urls()
        gathered: List[str] = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                gathered.extend(self._collect_media(path))
            elif is_image_file(path) or is_video_file(path):
                gathered.append(path)

        if gathered:
            self.files_dropped.emit(gathered)
            event.acceptProposedAction()

    def _collect_media(self, dir_path: str, max_files: int = 500) -> List[str]:
        found = []
        try:
            for root, _, files in os.walk(dir_path):
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    if is_image_file(fp) or is_video_file(fp):
                        found.append(fp)
                        if len(found) >= max_files:
                            return found
        except Exception:
            pass
        return found


class QueueItemWidget(QFrame):
    remove_requested = pyqtSignal(str)
    compare_requested = pyqtSignal(str, str)
    erase_requested = pyqtSignal(str)

    def __init__(self, item_data: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("QueueItemCard")
        self.item_id = item_data["id"]
        self.item_data = item_data

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # Thumbnail
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(40, 40)
        self.thumb_label.setStyleSheet("background-color: #171b26; border-radius: 6px; border: 1px solid #252d3d;")
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._load_thumb(item_data["path"], item_data["info"])
        layout.addWidget(self.thumb_label)

        # File details
        details_layout = QVBoxLayout()
        details_layout.setSpacing(2)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self.name_lbl = QLabel(item_data["info"]["name"])
        self.name_lbl.setStyleSheet("font-weight: 600; font-size: 13px; color: #ffffff;")
        name_row.addWidget(self.name_lbl)

        dim_str = f"{item_data['info'].get('width', 0)}×{item_data['info'].get('height', 0)}"
        self.size_lbl = QLabel(f"{dim_str} • {item_data['info']['size_str']}")
        self.size_lbl.setObjectName("SubtitleLabel")
        name_row.addWidget(self.size_lbl)
        name_row.addStretch()
        details_layout.addLayout(name_row)

        self.tag_lbl = QLabel(self._get_tag_text())
        self.tag_lbl.setStyleSheet("font-size: 11px; color: #818cf8;")
        details_layout.addWidget(self.tag_lbl)

        layout.addLayout(details_layout, stretch=1)

        # Actions & Status
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(6)

        self.status_badge = QLabel("Ready")
        self.status_badge.setObjectName("BadgeReady")
        actions_layout.addWidget(self.status_badge)

        self.erase_btn = QPushButton("Erase")
        self.erase_btn.setObjectName("SecondaryButton")
        self.erase_btn.setFixedHeight(26)
        self.erase_btn.setVisible(item_data["info"]["type"] == "image")
        self.erase_btn.setToolTip("Erase objects or watermarks from this image")
        self.erase_btn.clicked.connect(lambda: self.erase_requested.emit(self.item_data["path"]))
        actions_layout.addWidget(self.erase_btn)

        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setObjectName("SecondaryButton")
        self.compare_btn.setFixedHeight(26)
        self.compare_btn.setVisible(False)
        self.compare_btn.clicked.connect(self._on_compare)
        actions_layout.addWidget(self.compare_btn)

        self.open_btn = QPushButton("Open")
        self.open_btn.setObjectName("SecondaryButton")
        self.open_btn.setFixedHeight(26)
        self.open_btn.setVisible(False)
        self.open_btn.clicked.connect(self._on_open)
        actions_layout.addWidget(self.open_btn)

        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("SecondaryButton")
        self.remove_btn.setFixedSize(26, 26)
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.item_id))
        actions_layout.addWidget(self.remove_btn)

        layout.addLayout(actions_layout)

    def _get_tag_text(self) -> str:
        w = self.item_data["info"].get("width", 0)
        h = self.item_data["info"].get("height", 0)
        scale = self.item_data.get("scale", 4)
        model_name = self.item_data.get("model_tag", "realesrgan-x4plus")
        mtype = self.item_data["info"]["type"]

        if "rife" in model_name:
            if mtype == "image":
                return "RIFE requires video input"
            return f"60fps Motion • {model_name}"

        return f"Target: {w * scale}×{h * scale} ({scale}x) • {model_name}"

    def update_settings(self, scale: int, model_tag: str):
        self.item_data["scale"] = scale
        self.item_data["model_tag"] = model_tag
        self.tag_lbl.setText(self._get_tag_text())

    def set_status(self, status: str, pct: int = 0, out_path: Optional[str] = None):
        self.item_data["status"] = status
        if out_path:
            self.item_data["output_path"] = out_path

        if status == "pending":
            self.setObjectName("QueueItemCard")
            self.status_badge.setText("Ready")
            self.status_badge.setObjectName("BadgeReady")
            self.remove_btn.setEnabled(True)
            self.compare_btn.setVisible(False)
            self.open_btn.setVisible(False)
        elif status == "processing":
            self.setObjectName("QueueItemCardActive")
            self.status_badge.setText(f"{pct}%")
            self.status_badge.setObjectName("BadgeProcessing")
            self.remove_btn.setEnabled(False)
        elif status == "completed":
            self.setObjectName("QueueItemCard")
            self.status_badge.setText("Done")
            self.status_badge.setObjectName("BadgeSuccess")
            self.remove_btn.setEnabled(True)
            self.open_btn.setVisible(True)
            if self.item_data["info"]["type"] == "image":
                self.compare_btn.setVisible(True)
        elif status == "failed":
            self.setObjectName("QueueItemCard")
            self.status_badge.setText("Failed")
            self.status_badge.setObjectName("BadgeError")
            self.remove_btn.setEnabled(True)

        self.style().unpolish(self)
        self.style().polish(self)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)
        self.update()

    def _load_thumb(self, path: str, info: dict):
        if info["type"] == "video":
            self.thumb_label.setText("VID")
            self.thumb_label.setStyleSheet("font-size: 10px; font-weight: 700; color: #818cf8; background-color: #171c2b; border-radius: 6px;")
        else:
            pix = QPixmap(path)
            if not pix.isNull():
                scaled = pix.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                self.thumb_label.setPixmap(scaled)
            else:
                self.thumb_label.setText("IMG")
                self.thumb_label.setStyleSheet("font-size: 10px; font-weight: 700; color: #94a3b8; background-color: #171c2b; border-radius: 6px;")

    def _on_open(self):
        out_p = self.item_data.get("output_path")
        if out_p and os.path.exists(out_p):
            os.startfile(out_p)

    def _on_compare(self):
        inp = self.item_data["path"]
        out_p = self.item_data.get("output_path")
        if out_p and os.path.exists(out_p):
            self.compare_requested.emit(inp, out_p)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Upscaler")
        self.setMinimumSize(840, 560)
        self.resize(960, 640)
        self.setStyleSheet(DARK_STYLESHEET)
        self.setAcceptDrops(True)

        self.queue: List[dict] = []
        self.queue_widgets: Dict[str, QueueItemWidget] = {}
        self.recent_outputs: List[str] = []
        self.worker: Optional[BatchUpscaleWorker] = None

        self._build_ui()
        self._on_model_changed()

    def _build_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 14, 18, 14)
        main_layout.setSpacing(12)

        # 1. Header Bar
        header = QHBoxLayout()
        header.setSpacing(10)

        title_lbl = QLabel("Upscaler")
        title_lbl.setObjectName("HeaderTitle")
        header.addWidget(title_lbl)

        chip_lbl = QLabel("Vulkan GPU")
        chip_lbl.setObjectName("ChipLabel")
        header.addWidget(chip_lbl)

        header.addStretch()

        self.eraser_btn = QPushButton("Object Eraser")
        self.eraser_btn.setObjectName("SecondaryButton")
        self.eraser_btn.clicked.connect(lambda: self._open_object_eraser())
        header.addWidget(self.eraser_btn)

        self.compare_btn = QPushButton("Compare")
        self.compare_btn.setObjectName("SecondaryButton")
        self.compare_btn.clicked.connect(self._open_comparator)
        header.addWidget(self.compare_btn)

        self.engines_btn = QPushButton("Engines")
        self.engines_btn.setObjectName("SecondaryButton")
        self.engines_btn.clicked.connect(self._open_model_manager)
        header.addWidget(self.engines_btn)

        self.folder_btn = QPushButton("Output Folder")
        self.folder_btn.setObjectName("SecondaryButton")
        self.folder_btn.clicked.connect(self._open_output_folder)
        header.addWidget(self.folder_btn)

        main_layout.addLayout(header)

        # 2. Main Content: Stacked view between Drop Zone (empty) and Queue View (with items)
        self.stack = QStackedWidget()

        # Page 0: Empty State Drop Zone
        self.drop_zone = DropZoneWidget()
        self.drop_zone.files_dropped.connect(self._on_files_dropped)
        self.drop_zone.browse_files_clicked.connect(self._browse_files)
        self.drop_zone.browse_folder_clicked.connect(self._browse_folder)
        self.stack.addWidget(self.drop_zone)

        # Page 1: Queue View
        queue_container = QWidget()
        queue_layout = QVBoxLayout(queue_container)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setSpacing(8)

        # Queue Toolbar
        q_toolbar = QHBoxLayout()
        self.queue_count_lbl = QLabel("Queue (0)")
        self.queue_count_lbl.setStyleSheet("font-weight: 600; font-size: 13px; color: #ffffff;")
        q_toolbar.addWidget(self.queue_count_lbl)

        self.queue_sub_lbl = QLabel("")
        self.queue_sub_lbl.setObjectName("SubtitleLabel")
        q_toolbar.addWidget(self.queue_sub_lbl)

        q_toolbar.addStretch()

        add_files_btn = QPushButton("Add Files...")
        add_files_btn.setObjectName("SecondaryButton")
        add_files_btn.clicked.connect(self._browse_files)
        q_toolbar.addWidget(add_files_btn)

        add_folder_btn = QPushButton("Add Folder...")
        add_folder_btn.setObjectName("SecondaryButton")
        add_folder_btn.clicked.connect(self._browse_folder)
        q_toolbar.addWidget(add_folder_btn)

        clear_done_btn = QPushButton("Clear Done")
        clear_done_btn.setObjectName("SecondaryButton")
        clear_done_btn.clicked.connect(self._clear_completed)
        q_toolbar.addWidget(clear_done_btn)

        clear_all_btn = QPushButton("Clear All")
        clear_all_btn.setObjectName("SecondaryButton")
        clear_all_btn.clicked.connect(self._clear_queue)
        q_toolbar.addWidget(clear_all_btn)

        queue_layout.addLayout(q_toolbar)

        # Scrollable Queue List
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)

        self.queue_list_widget = QWidget()
        self.queue_list_layout = QVBoxLayout(self.queue_list_widget)
        self.queue_list_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_list_layout.setSpacing(6)
        self.queue_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.queue_scroll.setWidget(self.queue_list_widget)
        queue_layout.addWidget(self.queue_scroll)

        self.stack.addWidget(queue_container)
        main_layout.addWidget(self.stack, stretch=1)

        # 3. Bottom Control Bar (Pinned)
        bottom_bar = QFrame()
        bottom_bar.setObjectName("BottomBar")
        bottom_layout = QVBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(14, 10, 14, 10)
        bottom_layout.setSpacing(8)

        # Progress row (collapsible / only visible during or right after batch)
        self.progress_container = QWidget()
        prog_row = QVBoxLayout(self.progress_container)
        prog_row.setContentsMargins(0, 0, 0, 0)
        prog_row.setSpacing(4)

        prog_text_layout = QHBoxLayout()
        self.batch_status_text = QLabel("Ready")
        self.batch_status_text.setStyleSheet("font-size: 12px; color: #cbd5e1;")
        prog_text_layout.addWidget(self.batch_status_text)
        prog_text_layout.addStretch()

        self.batch_pct_label = QLabel("0%")
        self.batch_pct_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #818cf8;")
        prog_text_layout.addWidget(self.batch_pct_label)
        prog_row.addLayout(prog_text_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        prog_row.addWidget(self.progress_bar)

        self.progress_container.setVisible(False)
        bottom_layout.addWidget(self.progress_container)

        # Settings & Start Button Row
        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)

        # Model Selector
        m_box = QVBoxLayout()
        m_box.setSpacing(2)
        m_lbl = QLabel("Model")
        m_lbl.setObjectName("SubtitleLabel")
        m_box.addWidget(m_lbl)

        self.model_combo = QComboBox()
        for (m_type, m_name), cap in MODEL_CAPABILITIES.items():
            self.model_combo.addItem(cap["name"], (m_type, m_name))
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        m_box.addWidget(self.model_combo)
        controls_row.addLayout(m_box, stretch=3)

        # Scale Factor
        s_box = QVBoxLayout()
        s_box.setSpacing(2)
        self.scale_title = QLabel("Scale")
        self.scale_title.setObjectName("SubtitleLabel")
        s_box.addWidget(self.scale_title)

        self.scale_combo = QComboBox()
        self.scale_combo.currentIndexChanged.connect(self._update_all_queue_settings)
        s_box.addWidget(self.scale_combo)
        controls_row.addLayout(s_box, stretch=1)

        # Denoise
        d_box = QVBoxLayout()
        d_box.setSpacing(2)
        d_lbl = QLabel("Denoise")
        d_lbl.setObjectName("SubtitleLabel")
        d_box.addWidget(d_lbl)

        self.denoise_combo = QComboBox()
        self.denoise_combo.addItem("None (-1)", -1)
        self.denoise_combo.addItem("Conservative (0)", 0)
        self.denoise_combo.addItem("Low (1)", 1)
        self.denoise_combo.addItem("Medium (2)", 2)
        self.denoise_combo.addItem("High (3)", 3)
        self.denoise_combo.setCurrentIndex(1)
        self.denoise_combo.currentIndexChanged.connect(self._update_all_queue_settings)
        d_box.addWidget(self.denoise_combo)
        self.denoise_combo.setEnabled(False)
        controls_row.addLayout(d_box, stretch=1)

        # Output Folder
        out_box = QVBoxLayout()
        out_box.setSpacing(2)
        out_lbl = QLabel("Output Folder")
        out_lbl.setObjectName("SubtitleLabel")
        out_box.addWidget(out_lbl)

        self.output_btn = QPushButton(str(DEFAULT_OUTPUT_DIR.name))
        self.output_btn.setObjectName("SecondaryButton")
        self.output_btn.setToolTip(str(DEFAULT_OUTPUT_DIR))
        self.output_btn.clicked.connect(self._on_change_output_dir)
        out_box.addWidget(self.output_btn)
        self.current_output_dir = DEFAULT_OUTPUT_DIR
        controls_row.addLayout(out_box, stretch=2)

        # Action Button (Start / Cancel)
        btn_box = QVBoxLayout()
        btn_box.setSpacing(2)
        spacer_lbl = QLabel("")
        spacer_lbl.setObjectName("SubtitleLabel")
        btn_box.addWidget(spacer_lbl)

        self.start_btn = QPushButton("Start Upscaling")
        self.start_btn.setObjectName("PrimaryButton")
        self.start_btn.setFixedHeight(34)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._on_start_or_cancel)
        btn_box.addWidget(self.start_btn)
        controls_row.addLayout(btn_box, stretch=2)

        bottom_layout.addLayout(controls_row)
        main_layout.addWidget(bottom_bar)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        gathered: List[str] = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isdir(path):
                gathered.extend(self._collect_media_from_dir(path))
            elif is_image_file(path) or is_video_file(path):
                gathered.append(path)

        if gathered:
            self._on_files_dropped(gathered)
            event.acceptProposedAction()

    def _collect_media_from_dir(self, dir_path: str, max_files: int = 500) -> List[str]:
        found = []
        try:
            for root, _, files in os.walk(dir_path):
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    if is_image_file(fp) or is_video_file(fp):
                        found.append(fp)
                        if len(found) >= max_files:
                            return found
        except Exception:
            pass
        return found

    def _browse_files(self):
        file_filter = "Media Files (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mkv *.mov *.avi *.webm);;All Files (*.*)"
        files, _ = QFileDialog.getOpenFileNames(self, "Select Files to Upscale", "", file_filter)
        if files:
            self._on_files_dropped(files)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder Containing Media")
        if folder:
            files = self._collect_media_from_dir(folder)
            if files:
                self._on_files_dropped(files)

    def _on_files_dropped(self, file_paths: List[str]):
        current_model_tag = self._get_current_model_tag()
        scale = self.scale_combo.currentData() or 4

        for fp in file_paths:
            try:
                info = get_media_info(fp)
                item_id = str(uuid.uuid4())
                item_data = {
                    "id": item_id,
                    "path": fp,
                    "info": info,
                    "status": "pending",
                    "progress": 0,
                    "scale": scale,
                    "model_tag": current_model_tag,
                    "output_path": None,
                }
                self.queue.append(item_data)
                widget = QueueItemWidget(item_data, self)
                widget.remove_requested.connect(self._remove_queue_item)
                widget.compare_requested.connect(self._open_comparator_for_item)
                widget.erase_requested.connect(self._open_object_eraser)

                self.queue_widgets[item_id] = widget
                self.queue_list_layout.addWidget(widget)
            except Exception as e:
                print(f"Error inspecting {fp}: {e}")

        self._update_queue_ui_state()

    def _remove_queue_item(self, item_id: str):
        if item_id in self.queue_widgets:
            widget = self.queue_widgets.pop(item_id)
            self.queue_list_layout.removeWidget(widget)
            widget.deleteLater()

        self.queue = [item for item in self.queue if item["id"] != item_id]
        self._update_queue_ui_state()

    def _clear_completed(self):
        to_remove = [item["id"] for item in self.queue if item["status"] == "completed"]
        for item_id in to_remove:
            self._remove_queue_item(item_id)

    def _clear_queue(self):
        for item_id, widget in list(self.queue_widgets.items()):
            self.queue_list_layout.removeWidget(widget)
            widget.deleteLater()
        self.queue_widgets.clear()
        self.queue.clear()
        self._update_queue_ui_state()

    def _update_queue_ui_state(self):
        total = len(self.queue)
        pending = sum(1 for item in self.queue if item["status"] == "pending")
        completed = sum(1 for item in self.queue if item["status"] == "completed")

        if total == 0:
            self.stack.setCurrentIndex(0)
            self.start_btn.setEnabled(False)
            self.start_btn.setText("Start Upscaling")
            return

        self.stack.setCurrentIndex(1)
        self.queue_count_lbl.setText(f"Queue ({total})")
        self.queue_sub_lbl.setText(f"• {pending} Pending • {completed} Done" if completed else f"• {pending} Pending")

        is_running = self.worker is not None and self.worker.isRunning()
        if is_running:
            self.start_btn.setEnabled(True)
            self.start_btn.setText("Cancel")
            self.start_btn.setObjectName("DangerButton")
        else:
            self.start_btn.setObjectName("PrimaryButton")
            can_start = pending > 0
            self.start_btn.setEnabled(can_start)
            self.start_btn.setText(f"Start Upscaling ({pending})" if pending else "All Done")

        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)

    def _get_current_model_tag(self) -> str:
        model_type, model_name = self.model_combo.currentData()
        denoise = self.denoise_combo.currentData() if model_type == "realcugan" else 0
        return get_model_tag(model_type, model_name, denoise)

    def _on_model_changed(self):
        data = self.model_combo.currentData()
        if not data:
            return
        model_type, model_name = data
        cap = MODEL_CAPABILITIES.get((model_type, model_name), {
            "scales": [(4, "4x")],
            "supports_denoise": False,
        })

        self.scale_combo.blockSignals(True)
        prev_scale = self.scale_combo.currentData()
        self.scale_combo.clear()

        for sc_val, sc_label in cap.get("scales", []):
            self.scale_combo.addItem(sc_label, sc_val)

        idx = self.scale_combo.findData(prev_scale)
        if idx >= 0:
            self.scale_combo.setCurrentIndex(idx)
        self.scale_combo.blockSignals(False)

        self.scale_title.setText("Motion" if model_type == "rife" else "Scale")
        self.scale_combo.setEnabled(model_type != "rife")
        self.denoise_combo.setEnabled(cap.get("supports_denoise", False))

        self._update_all_queue_settings()
        self._update_queue_ui_state()

    def _update_all_queue_settings(self):
        current_tag = self._get_current_model_tag()
        scale = self.scale_combo.currentData() or 4
        for item in self.queue:
            if item["status"] == "pending":
                item_id = item["id"]
                if item_id in self.queue_widgets:
                    self.queue_widgets[item_id].update_settings(scale, current_tag)

    def _on_change_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory", str(self.current_output_dir))
        if folder:
            self.current_output_dir = Path(folder)
            self.output_btn.setText(self.current_output_dir.name)
            self.output_btn.setToolTip(str(self.current_output_dir))

    def _on_start_or_cancel(self):
        if self.worker and self.worker.isRunning():
            self.batch_status_text.setText("Cancelling...")
            self.worker.cancel()
            return

        pending_items = [item for item in self.queue if item["status"] == "pending"]
        if not pending_items:
            return

        model_type, model_name = self.model_combo.currentData()
        scale = self.scale_combo.currentData() or 4
        denoise = self.denoise_combo.currentData() if model_type == "realcugan" else 0
        output_dir = self.current_output_dir.resolve()

        installed = check_all_installed()
        if not installed.get(model_type, False):
            resp = QMessageBox.question(
                self,
                "Model Engine Not Installed",
                f"The {model_type} engine is not installed.\nOpen the Engines manager to download it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if resp == QMessageBox.StandardButton.Yes:
                self._open_model_manager()
            return

        tasks: List[QueueTask] = [
            QueueTask(
                task_id=item["id"],
                input_path=Path(item["path"]),
                output_dir=output_dir,
                model_type=model_type,
                model_name=model_name,
                scale=scale,
                denoise=denoise,
            )
            for item in pending_items
        ]

        self.progress_container.setVisible(True)
        self.progress_bar.setValue(0)
        self.batch_pct_label.setText("0%")
        self.batch_status_text.setText(f"Starting batch of {len(tasks)} files...")

        self.worker = BatchUpscaleWorker(tasks)
        self.worker.item_started.connect(self._on_worker_item_started)
        self.worker.item_progress.connect(self._on_worker_item_progress)
        self.worker.item_finished.connect(self._on_worker_item_finished)
        self.worker.batch_progress.connect(self._on_worker_batch_progress)
        self.worker.batch_finished.connect(self._on_worker_batch_finished)
        self.worker.start()

        self._update_queue_ui_state()

    def _on_worker_item_started(self, idx: int, total: int, item_name: str):
        if self.worker and idx < len(self.worker.tasks):
            task_id = self.worker.tasks[idx].task_id
            if task_id in self.queue_widgets:
                self.queue_widgets[task_id].set_status("processing", pct=0)

        self.batch_status_text.setText(f"[{idx + 1}/{total}] {item_name}")

    def _on_worker_item_progress(self, idx: int, pct: int, msg: str):
        if self.worker and idx < len(self.worker.tasks):
            task_id = self.worker.tasks[idx].task_id
            if task_id in self.queue_widgets:
                self.queue_widgets[task_id].set_status("processing", pct=pct)

    def _on_worker_item_finished(self, idx: int, success: bool, output_path: str, msg: str):
        if self.worker and idx < len(self.worker.tasks):
            task_id = self.worker.tasks[idx].task_id
            if task_id in self.queue_widgets:
                status = "completed" if success else "failed"
                self.queue_widgets[task_id].set_status(status, out_path=output_path if success else None)
                if success and output_path:
                    self.recent_outputs.append(output_path)

        self._update_queue_ui_state()

    def _on_worker_batch_progress(self, done_count: int, total_count: int, overall_pct: int):
        self.progress_bar.setValue(overall_pct)
        self.batch_pct_label.setText(f"{overall_pct}%")

    def _on_worker_batch_finished(self, success_count: int, fail_count: int, results: list):
        self.progress_bar.setValue(100)
        self.batch_pct_label.setText("100%")

        total = success_count + fail_count
        summary = f"Finished: {success_count}/{total} files upscaled."
        if fail_count > 0:
            summary += f" ({fail_count} failed)"
        self.batch_status_text.setText(summary)

        self._update_queue_ui_state()

    def _open_output_folder(self):
        folder = self.current_output_dir
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)

    def _open_comparator_for_item(self, input_path: str, output_path: str):
        candidates = list(self.recent_outputs)
        if input_path not in candidates and os.path.exists(input_path):
            candidates.insert(0, input_path)
        dlg = ImageComparatorDialog(recent_files=candidates, initial_a=input_path, initial_b=output_path, parent=self)
        dlg.exec()

    def _open_comparator(self):
        candidates = list(self.recent_outputs)
        if self.current_output_dir.exists():
            for f in sorted(self.current_output_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if is_image_file(f) and str(f) not in candidates:
                    candidates.append(str(f))

        dlg = ImageComparatorDialog(recent_files=candidates, parent=self)
        dlg.exec()

    def _open_model_manager(self):
        dlg = ModelManagerDialog(self)
        dlg.exec()

    def _open_object_eraser(self, image_path: Optional[str] = None):
        if not image_path and self.queue:
            for it in self.queue:
                if it["info"]["type"] == "image":
                    image_path = it["path"]
                    break
        dlg = ObjectEraserDialog(initial_image_path=image_path, parent=self)
        dlg.send_to_queue_requested.connect(self._on_erased_image_sent)
        dlg.exec()

    def _on_erased_image_sent(self, cleaned_image_path: str):
        self._on_files_dropped([cleaned_image_path])

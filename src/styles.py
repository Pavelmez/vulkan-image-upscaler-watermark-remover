DARK_STYLESHEET = """
/* Window & Base */
QMainWindow, QDialog {
    background-color: #0d0f17;
    color: #e2e8f0;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 10pt;
}

QWidget#CentralWidget {
    background-color: #0d0f17;
}

/* Headings and Labels */
QLabel {
    color: #cbd5e1;
}

QLabel#HeaderTitle {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.2px;
}

QLabel#ChipLabel {
    background-color: #171c2b;
    color: #818cf8;
    border: 1px solid #28304c;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#SubtitleLabel {
    font-size: 12px;
    color: #64748b;
}

QLabel#SectionTitle {
    font-size: 12px;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* Drop Zone Area */
QFrame#DropZoneBox {
    background-color: #121520;
    border: 1.5px dashed #2b334a;
    border-radius: 10px;
}

QFrame#DropZoneBox:hover {
    border-color: #4f5878;
    background-color: #151928;
}

QFrame#DropZoneBoxActive {
    border: 1.5px dashed #3b82f6;
    background-color: #141c30;
}

QLabel#DropTitle {
    font-size: 15px;
    font-weight: 600;
    color: #f1f5f9;
}

QLabel#DropSubtitle {
    font-size: 12px;
    color: #64748b;
}

/* Cards & Containers */
QFrame#BottomBar {
    background-color: #131622;
    border: 1px solid #212638;
    border-radius: 10px;
}

QFrame#Card {
    background-color: #131622;
    border: 1px solid #212638;
    border-radius: 8px;
}

/* Queue Item Cards */
QFrame#QueueItemCard {
    background-color: #131622;
    border: 1px solid #1e2333;
    border-radius: 8px;
}

QFrame#QueueItemCard:hover {
    border-color: #2e374f;
    background-color: #161a29;
}

QFrame#QueueItemCardActive {
    background-color: #171d30;
    border: 1px solid #3b82f6;
    border-radius: 8px;
}

/* Status Badges */
QLabel#BadgeReady {
    background-color: #1c2233;
    color: #94a3b8;
    border: 1px solid #28304a;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#BadgeProcessing {
    background-color: #172554;
    color: #93c5fd;
    border: 1px solid #1d4ed8;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#BadgeSuccess {
    background-color: #064e3b;
    color: #6ee7b7;
    border: 1px solid #047857;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#BadgeError {
    background-color: #450a0a;
    color: #fca5a5;
    border: 1px solid #991b1b;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
}

/* Primary Action Buttons */
QPushButton#PrimaryButton {
    background-color: #2563eb;
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
    padding: 5px 14px;
    border-radius: 6px;
    border: 1px solid #3b82f6;
    text-align: center;
}

QPushButton#PrimaryButton:hover {
    background-color: #1d4ed8;
    border-color: #60a5fa;
}

QPushButton#PrimaryButton:pressed {
    background-color: #1e40af;
}

QPushButton#PrimaryButton:disabled {
    background-color: #1a2030;
    color: #475569;
    border-color: #242c40;
}

/* Secondary Buttons */
QPushButton#SecondaryButton {
    background-color: #171b28;
    color: #cbd5e1;
    font-size: 12px;
    font-weight: 500;
    padding: 5px 10px;
    border-radius: 6px;
    border: 1px solid #283044;
    text-align: center;
}

QPushButton#SecondaryButton:hover {
    background-color: #212738;
    border-color: #3b4660;
    color: #ffffff;
}

QPushButton#SecondaryButton:pressed {
    background-color: #131620;
}

QPushButton#SecondaryButton:disabled {
    color: #475569;
    border-color: #1c2230;
    background-color: #121520;
}

/* Danger Button */
QPushButton#DangerButton {
    background-color: #7f1d1d;
    color: #ffffff;
    font-size: 12px;
    font-weight: 600;
    padding: 6px 14px;
    border-radius: 6px;
    border: 1px solid #991b1b;
}

QPushButton#DangerButton:hover {
    background-color: #991b1b;
    border-color: #b91c1c;
}

QPushButton#DangerButton:pressed {
    background-color: #631414;
}

/* Combo Boxes */
QComboBox {
    background-color: #161a26;
    border: 1px solid #283044;
    border-radius: 6px;
    padding: 5px 10px;
    color: #f1f5f9;
    font-size: 12px;
    min-height: 22px;
}

QComboBox:hover {
    border-color: #3d4966;
}

QComboBox:focus {
    border-color: #3b82f6;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #283044;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: #1a1f2e;
}

QComboBox::down-arrow {
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #94a3b8;
}

QComboBox QAbstractItemView {
    background-color: #151824;
    border: 1px solid #2c354a;
    color: #f1f5f9;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}

QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 4px 8px;
}

/* Progress Bar */
QProgressBar {
    border: none;
    background-color: #1a1e2c;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 3px;
}

/* Scroll Area & Scrollbars */
QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    border: none;
    background: #0d0f17;
    width: 6px;
    border-radius: 3px;
}

QScrollBar::handle:vertical {
    background: #252b3d;
    border-radius: 3px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #3a435c;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

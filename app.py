from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pdf_compressor import (
    PROFILES,
    CompressionCancelled,
    CompressionError,
    CompressionResult,
    CompressionSettings,
    compress_pdf,
    format_bytes,
    inspect_pdf,
    suggested_output_path,
)


APP_NAME = "ComprimiPDF"


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def application_icon() -> QIcon:
    icon_name = "dog_mascot.icns" if sys.platform == "darwin" else "dog_mascot.ico"
    icon = QIcon(str(resource_path(f"assets/{icon_name}")))
    if icon.isNull():
        icon = QIcon(str(resource_path("assets/dog_mascot.png")))
    return icon if not icon.isNull() else make_icon()


class DropList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setMinimumHeight(178)
        self.setToolTip("Trascina qui uno o più file PDF")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(url.toLocalFile().lower().endswith(".pdf") for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile().lower().endswith(".pdf")]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.count() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor("#7a8799"))
            painter.drawText(
                self.viewport().rect().adjusted(18, 18, -18, -18),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                "Trascina qui i PDF oppure usa “Aggiungi PDF”",
            )


class CompressionWorker(QObject):
    progress = Signal(int, str)
    file_done = Signal(object)
    file_error = Signal(str, str)
    finished = Signal(bool)

    def __init__(self, files: list[Path], output_dir: Path | None, settings: CompressionSettings) -> None:
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.settings = settings
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        cancelled = False
        count = len(self.files)
        for file_index, source in enumerate(self.files):
            if self.cancel_event.is_set():
                cancelled = True
                break
            destination = suggested_output_path(source, self.output_dir)

            def update(percent: int, message: str) -> None:
                overall = round((file_index + percent / 100) / count * 100)
                self.progress.emit(overall, f"{source.name} - {message}")

            try:
                result = compress_pdf(source, destination, self.settings, update, self.cancel_event)
                self.file_done.emit(result)
            except CompressionCancelled:
                cancelled = True
                break
            except Exception as exc:
                self.file_error.emit(str(source), str(exc))
        self.finished.emit(cancelled)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.files: list[Path] = []
        self.results: list[CompressionResult] = []
        self.output_dir: Path | None = None
        self.worker: CompressionWorker | None = None
        self.thread: QThread | None = None
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(900, 700)
        self.resize(980, 760)
        self.setWindowIcon(application_icon())
        self._build_ui()
        self._apply_style()
        self._select_profile("portal")

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(30, 24, 30, 24)
        outer.setSpacing(18)

        title_row = QHBoxLayout()
        badge = QLabel()
        badge.setObjectName("mascot")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(82, 82)
        mascot = QPixmap(str(resource_path("assets/dog_mascot.png")))
        if mascot.isNull():
            badge.setText("PDF")
        else:
            badge.setPixmap(mascot.scaled(82, 82, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        title_box = QVBoxLayout()
        title = QLabel("ComprimiPDF")
        title.setObjectName("title")
        subtitle = QLabel("PDF più leggeri, senza sorprese su font e compatibilità")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        title_row.addWidget(badge)
        title_row.addLayout(title_box)
        title_row.addStretch()
        outer.addLayout(title_row)

        content = QGridLayout()
        content.setHorizontalSpacing(18)
        content.setVerticalSpacing(16)

        files_card, files_layout = self._card("1. Scegli i PDF")
        action_row = QHBoxLayout()
        self.add_button = QPushButton("+  Aggiungi PDF")
        self.add_button.setObjectName("primarySmall")
        self.remove_button = QPushButton("Rimuovi selezionati")
        self.clear_button = QPushButton("Svuota")
        action_row.addWidget(self.add_button)
        action_row.addWidget(self.remove_button)
        action_row.addWidget(self.clear_button)
        action_row.addStretch()
        files_layout.addLayout(action_row)
        self.file_list = DropList()
        files_layout.addWidget(self.file_list)
        self.file_summary = QLabel("Nessun file selezionato")
        self.file_summary.setObjectName("muted")
        files_layout.addWidget(self.file_summary)
        content.addWidget(files_card, 0, 0, 1, 2)

        profile_card, profile_layout = self._card("2. Scegli il tipo di compressione")
        self.profile_combo = QComboBox()
        for key, profile in PROFILES.items():
            self.profile_combo.addItem(profile["name"], key)
        profile_layout.addWidget(self.profile_combo)
        self.profile_description = QLabel()
        self.profile_description.setWordWrap(True)
        self.profile_description.setObjectName("infoBox")
        profile_layout.addWidget(self.profile_description)
        warning = QLabel("✓ Nei primi quattro profili il testo resta selezionabile e i font non vengono sostituiti.")
        warning.setWordWrap(True)
        warning.setObjectName("successText")
        profile_layout.addWidget(warning)
        content.addWidget(profile_card, 1, 0)

        options_card, options_layout = self._card("3. Opzioni")
        quality_row = QHBoxLayout()
        quality_row.addWidget(QLabel("Qualità immagini"))
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(30, 95)
        self.quality_value = QLabel()
        self.quality_value.setFixedWidth(42)
        quality_row.addWidget(self.quality_slider, 1)
        quality_row.addWidget(self.quality_value)
        options_layout.addLayout(quality_row)

        dpi_row = QHBoxLayout()
        dpi_row.addWidget(QLabel("Risoluzione massima"))
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(72, 300)
        self.dpi_spin.setSuffix(" dpi")
        dpi_row.addStretch()
        dpi_row.addWidget(self.dpi_spin)
        options_layout.addLayout(dpi_row)

        self.grayscale_check = QCheckBox("Converti le immagini in scala di grigi")
        self.metadata_check = QCheckBox("Rimuovi autore, titolo e altri metadati")
        options_layout.addWidget(self.grayscale_check)
        options_layout.addWidget(self.metadata_check)

        output_row = QHBoxLayout()
        self.output_label = QLabel("Salva accanto agli originali")
        self.output_label.setObjectName("muted")
        self.output_label.setWordWrap(True)
        self.output_button = QPushButton("Cambia cartella…")
        output_row.addWidget(self.output_label, 1)
        output_row.addWidget(self.output_button)
        options_layout.addLayout(output_row)
        content.addWidget(options_card, 1, 1)
        content.setColumnStretch(0, 1)
        content.setColumnStretch(1, 1)
        outer.addLayout(content, 1)

        bottom = QFrame()
        bottom.setObjectName("bottomBar")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(18, 14, 18, 14)
        status_row = QHBoxLayout()
        self.status_label = QLabel("Pronto")
        self.status_label.setObjectName("status")
        self.open_folder_button = QPushButton("Apri cartella risultati")
        self.open_folder_button.hide()
        self.cancel_button = QPushButton("Annulla")
        self.cancel_button.hide()
        self.start_button = QPushButton("Comprimi PDF")
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumWidth(175)
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.open_folder_button)
        status_row.addWidget(self.cancel_button)
        status_row.addWidget(self.start_button)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        bottom_layout.addLayout(status_row)
        bottom_layout.addWidget(self.progress_bar)
        outer.addWidget(bottom)

        self.setCentralWidget(root)
        self.add_button.clicked.connect(self._choose_files)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_files)
        self.file_list.files_dropped.connect(self._add_files)
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        self.quality_slider.valueChanged.connect(lambda value: self.quality_value.setText(f"{value}%"))
        self.output_button.clicked.connect(self._choose_output_dir)
        self.start_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self._cancel)
        self.open_folder_button.clicked.connect(self._open_output_folder)

    def _card(self, heading: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 17)
        layout.setSpacing(12)
        label = QLabel(heading)
        label.setObjectName("sectionTitle")
        layout.addWidget(label)
        return frame, layout

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f3f6fb; color: #1f2937; font-family: "Segoe UI"; font-size: 10.5pt; }
            QLabel, QCheckBox { background: transparent; }
            QLabel#title { font-size: 23pt; font-weight: 700; color: #172033; }
            QLabel#subtitle, QLabel#muted { color: #667085; }
            QLabel#mascot { background: transparent; }
            QFrame#card { background: white; border: 1px solid #dfe5ef; border-radius: 12px; }
            QLabel#sectionTitle { font-size: 12pt; font-weight: 650; color: #172033; }
            QLabel#infoBox { background: #eff6ff; color: #1e4d91; border: 1px solid #cfe0ff; border-radius: 8px; padding: 11px; }
            QLabel#successText { color: #287554; }
            QListWidget { background: #fbfcfe; border: 1px dashed #9eb2cf; border-radius: 9px; padding: 7px; outline: none; }
            QListWidget::item { padding: 9px; border-radius: 6px; }
            QListWidget::item:selected { background: #dbeafe; color: #173b70; }
            QComboBox, QSpinBox { background: white; border: 1px solid #b9c4d4; border-radius: 7px; padding: 7px 9px; min-height: 22px; }
            QComboBox:focus, QSpinBox:focus { border: 1px solid #2563eb; }
            QPushButton { background: #ffffff; border: 1px solid #b9c4d4; border-radius: 7px; padding: 8px 12px; }
            QPushButton:hover { background: #edf3fb; border-color: #8da4c4; }
            QPushButton:pressed { background: #e1e9f5; }
            QPushButton:disabled { color: #98a2b3; background: #eef1f5; }
            QPushButton#primary, QPushButton#primarySmall { background: #2563eb; border-color: #2563eb; color: white; font-weight: 650; }
            QPushButton#primary { padding: 11px 20px; }
            QPushButton#primary:hover, QPushButton#primarySmall:hover { background: #1d4ed8; }
            QFrame#bottomBar { background: white; border: 1px solid #dfe5ef; border-radius: 12px; }
            QLabel#status { font-weight: 600; }
            QProgressBar { border: none; background: #e6ebf2; border-radius: 4px; height: 8px; }
            QProgressBar::chunk { background: #2563eb; border-radius: 4px; }
            QSlider::groove:horizontal { height: 5px; background: #d7deea; border-radius: 2px; }
            QSlider::handle:horizontal { background: #2563eb; width: 16px; margin: -6px 0; border-radius: 8px; }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 17px; height: 17px; }
        """)

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Scegli i PDF", "", "Documenti PDF (*.pdf)")
        self._add_files(paths)

    def _add_files(self, paths: list[str]) -> None:
        existing = {str(path).lower() for path in self.files}
        errors: list[str] = []
        for raw_path in paths:
            path = Path(raw_path).resolve()
            if str(path).lower() in existing or path.suffix.lower() != ".pdf":
                continue
            try:
                details = inspect_pdf(path)
                suffix = " - protetto da password" if details["encrypted"] else f" - {details['pages']} pagine"
                if details["signed"]:
                    suffix += " - firmato"
                item = QListWidgetItem(f"{path.name}   ·   {format_bytes(path.stat().st_size)}{suffix}")
                item.setToolTip(str(path))
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                self.file_list.addItem(item)
                self.files.append(path)
                existing.add(str(path).lower())
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        self._update_file_summary()
        if errors:
            QMessageBox.warning(self, "File non aggiunti", "\n".join(errors))

    def _remove_selected(self) -> None:
        rows = sorted({self.file_list.row(item) for item in self.file_list.selectedItems()}, reverse=True)
        for row in rows:
            self.file_list.takeItem(row)
            self.files.pop(row)
        self._update_file_summary()

    def _clear_files(self) -> None:
        self.files.clear()
        self.file_list.clear()
        self._update_file_summary()

    def _update_file_summary(self) -> None:
        total = sum(path.stat().st_size for path in self.files if path.exists())
        if self.files:
            self.file_summary.setText(f"{len(self.files)} file · {format_bytes(total)} complessivi")
        else:
            self.file_summary.setText("Nessun file selezionato")
        self.start_button.setEnabled(bool(self.files) and self.thread is None)

    def _profile_changed(self) -> None:
        key = self.profile_combo.currentData()
        profile = PROFILES[key]
        self.profile_description.setText(profile["description"])
        self.quality_slider.setValue(profile["quality"])
        if profile["dpi"]:
            self.dpi_spin.setValue(profile["dpi"])
        lossless = key == "lossless"
        self.quality_slider.setEnabled(not lossless)
        self.dpi_spin.setEnabled(not lossless)
        self.grayscale_check.setEnabled(not lossless)

    def _select_profile(self, key: str) -> None:
        index = self.profile_combo.findData(key)
        self.profile_combo.setCurrentIndex(index)
        self._profile_changed()

    def _choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Cartella dei PDF compressi")
        if folder:
            self.output_dir = Path(folder)
            self.output_label.setText(str(self.output_dir))

    def _start(self) -> None:
        if not self.files:
            return
        signed = []
        encrypted = []
        for path in self.files:
            details = inspect_pdf(path)
            if details["signed"]:
                signed.append(path.name)
            if details["encrypted"]:
                encrypted.append(path.name)
        if encrypted:
            QMessageBox.warning(self, "PDF protetti", "Questi PDF richiedono una password e saranno segnalati come errore:\n\n" + "\n".join(encrypted))
        if signed:
            answer = QMessageBox.warning(
                self,
                "Firma digitale",
                "La compressione invalida le firme digitali presenti in:\n\n" + "\n".join(signed) + "\n\nContinuare comunque?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if self.profile_combo.currentData() == "raster":
            answer = QMessageBox.question(
                self,
                "Massima compatibilità",
                "Questa modalità elimina testo selezionabile, link, moduli e segnalibri. Vuoi continuare?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        settings = CompressionSettings(
            profile=self.profile_combo.currentData(),
            jpeg_quality=self.quality_slider.value(),
            max_dpi=self.dpi_spin.value(),
            grayscale=self.grayscale_check.isChecked(),
            remove_metadata=self.metadata_check.isChecked(),
        )
        self.results.clear()
        self.open_folder_button.hide()
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.cancel_button.show()
        self._set_controls_enabled(False)
        self.status_label.setText("Preparazione…")

        self.thread = QThread(self)
        self.worker = CompressionWorker(list(self.files), self.output_dir, settings)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.file_error.connect(self._on_file_error)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.add_button, self.remove_button, self.clear_button, self.file_list, self.profile_combo, self.output_button, self.start_button):
            widget.setEnabled(enabled)
        if enabled:
            self.metadata_check.setEnabled(True)
            self._profile_changed()
        else:
            self.quality_slider.setEnabled(False)
            self.dpi_spin.setEnabled(False)
            self.grayscale_check.setEnabled(False)
            self.metadata_check.setEnabled(False)

    def _on_progress(self, percent: int, message: str) -> None:
        self.progress_bar.setValue(percent)
        self.status_label.setText(message)

    def _on_file_done(self, result: CompressionResult) -> None:
        self.results.append(result)

    def _on_file_error(self, source: str, message: str) -> None:
        QMessageBox.critical(self, "Compressione non riuscita", f"{Path(source).name}\n\n{message}")

    def _on_finished(self, cancelled: bool) -> None:
        self.thread = None
        self.worker = None
        self.cancel_button.hide()
        self._set_controls_enabled(True)
        self._update_file_summary()
        if cancelled:
            self.status_label.setText("Operazione annullata")
            return
        self.progress_bar.setValue(100)
        if self.results:
            original = sum(result.original_bytes for result in self.results)
            compressed = sum(result.compressed_bytes for result in self.results)
            saving = (1 - compressed / original) * 100 if original else 0
            if saving >= 0:
                summary = f"Completato: {format_bytes(original)} → {format_bytes(compressed)} · riduzione {saving:.1f}%"
            else:
                summary = f"Completato: il risultato è più grande di {abs(saving):.1f}%"
            self.status_label.setText(summary)
            self.open_folder_button.show()
        else:
            self.status_label.setText("Nessun file compresso")

    def _cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status_label.setText("Annullamento in corso…")
            self.cancel_button.setEnabled(False)

    def _open_output_folder(self) -> None:
        if self.results:
            QDesktopServices.openUrl(self.results[-1].output_path.parent.as_uri())

    def closeEvent(self, event) -> None:
        if self.thread and self.thread.isRunning():
            answer = QMessageBox.question(self, "Compressione in corso", "Annullare la compressione e chiudere?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self.worker:
                self.worker.cancel()
            self.status_label.setText("Annullamento in corso…")
            self.setEnabled(False)
            self.thread.finished.connect(self.close)
            event.ignore()
            return
        event.accept()


def make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2563eb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 13, 13)
    painter.setPen(QPen(QColor("white"), 3))
    font = QFont("Segoe UI", 12, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "PDF")
    painter.end()
    return QIcon(pixmap)


def main() -> int:
    if sys.platform == "win32":
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LocalTools.ComprimiPDF")
        except Exception:
            pass
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setOrganizationName("LocalTools")
    application.setStyle("Fusion")
    application.setWindowIcon(application_icon())
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())

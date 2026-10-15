from __future__ import annotations

import io
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf as fitz
from PIL import Image, ImageOps


ProgressCallback = Callable[[int, str], None]


class CompressionError(RuntimeError):
    pass


class CompressionCancelled(CompressionError):
    pass


@dataclass(frozen=True)
class CompressionSettings:
    profile: str = "portal"
    jpeg_quality: int = 86
    max_dpi: int = 170
    grayscale: bool = False
    remove_metadata: bool = False


@dataclass(frozen=True)
class CompressionResult:
    input_path: Path
    output_path: Path
    original_bytes: int
    compressed_bytes: int
    pages: int
    images_optimized: int
    rasterized: bool

    @property
    def saving_percent(self) -> float:
        if not self.original_bytes:
            return 0.0
        return (1 - self.compressed_bytes / self.original_bytes) * 100


PROFILES = {
    "lossless": {
        "name": "Senza perdita",
        "description": "Riordina e comprime i flussi senza ricampionare le immagini. Testo, font e qualità restano invariati.",
        "quality": 100,
        "dpi": 0,
        "raster": False,
    },
    "portal": {
        "name": "Compatibile portali",
        "description": "Riduce soltanto le immagini e non sostituisce, converte o elimina i font. Scelta consigliata per upload online.",
        "quality": 86,
        "dpi": 170,
        "raster": False,
    },
    "balanced": {
        "name": "Bilanciata",
        "description": "Buon compromesso per documenti da leggere a schermo o inviare per e-mail.",
        "quality": 74,
        "dpi": 145,
        "raster": False,
    },
    "strong": {
        "name": "Compressione forte",
        "description": "Riduce maggiormente le immagini. Il testo rimane selezionabile e i font non vengono cambiati.",
        "quality": 57,
        "dpi": 110,
        "raster": False,
    },
    "raster": {
        "name": "Massima compatibilità",
        "description": "Trasforma ogni pagina in un'immagine. Elimina problemi di font, ma anche ricerca, selezione testo, link e moduli.",
        "quality": 78,
        "dpi": 150,
        "raster": True,
    },
}


def format_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"


def suggested_output_path(source: Path, output_dir: Path | None = None) -> Path:
    folder = output_dir or source.parent
    candidate = folder / f"{source.stem}_compresso.pdf"
    counter = 2
    while candidate.exists():
        candidate = folder / f"{source.stem}_compresso_{counter}.pdf"
        counter += 1
    return candidate


def inspect_pdf(path: str | Path) -> dict:
    source = Path(path)
    try:
        with fitz.open(source) as document:
            if document.needs_pass:
                return {"pages": 0, "encrypted": True, "signed": False}
            signed = False
            for page in document:
                widgets = page.widgets()
                if widgets and any(widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE for widget in widgets):
                    signed = True
                    break
            return {"pages": document.page_count, "encrypted": False, "signed": signed}
    except Exception as exc:
        raise CompressionError(f"PDF non valido o non leggibile: {exc}") from exc


def compress_pdf(
    input_path: str | Path,
    output_path: str | Path,
    settings: CompressionSettings,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> CompressionResult:
    source = Path(input_path).resolve()
    destination = Path(output_path).resolve()
    if source == destination:
        raise CompressionError("Il file di destinazione deve essere diverso dall'originale.")
    if settings.profile not in PROFILES:
        raise CompressionError("Profilo di compressione sconosciuto.")
    if not source.is_file():
        raise CompressionError("Il file sorgente non esiste.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_handle, temp_name = tempfile.mkstemp(prefix="compresspdf_", suffix=".pdf", dir=destination.parent)
    os.close(temp_handle)
    temporary = Path(temp_name)
    # MuPDF crea il file di output e su Windows non sovrascrive un file vuoto già esistente.
    temporary.unlink()
    try:
        _notify(progress, 2, "Apertura PDF")
        if PROFILES[settings.profile]["raster"]:
            pages, optimized = _compress_raster(source, temporary, settings, progress, cancel_event)
            rasterized = True
        else:
            pages, optimized = _compress_preserving_text(source, temporary, settings, progress, cancel_event)
            rasterized = False

        _check_cancelled(cancel_event)
        _notify(progress, 96, "Verifica del risultato")
        _validate_pdf(temporary, pages)
        os.replace(temporary, destination)
        _notify(progress, 100, "Completato")
        return CompressionResult(
            input_path=source,
            output_path=destination,
            original_bytes=source.stat().st_size,
            compressed_bytes=destination.stat().st_size,
            pages=pages,
            images_optimized=optimized,
            rasterized=rasterized,
        )
    except (CompressionError, CompressionCancelled):
        raise
    except Exception as exc:
        raise CompressionError(str(exc)) from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except PermissionError:
            pass


def _compress_preserving_text(
    source: Path,
    destination: Path,
    settings: CompressionSettings,
    progress: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> tuple[int, int]:
    with fitz.open(source) as document:
        if document.needs_pass:
            raise CompressionError("Il PDF è protetto da password. Rimuovere la protezione e riprovare.")
        pages = document.page_count
        if pages == 0:
            raise CompressionError("Il PDF non contiene pagine.")

        optimized = 0
        if settings.profile != "lossless":
            occurrences = _collect_image_occurrences(document)
            total = max(1, len(occurrences))
            for index, (xref, info) in enumerate(occurrences.items(), start=1):
                _check_cancelled(cancel_event)
                if _optimize_image(document, xref, info, settings):
                    optimized += 1
                percent = 8 + round(index / total * 78)
                _notify(progress, percent, f"Ottimizzazione immagini {index}/{total}")
        else:
            _notify(progress, 65, "Compressione senza perdita")

        if settings.remove_metadata:
            document.set_metadata({})

        _notify(progress, 90, "Scrittura del nuovo PDF")
        document.save(
            destination,
            garbage=4,
            clean=False,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            use_objstms=0,
        )
        return pages, optimized


def _collect_image_occurrences(document: fitz.Document) -> dict[int, dict]:
    occurrences: dict[int, dict] = {}
    for page in document:
        for image in page.get_images(full=True):
            xref = image[0]
            smask = image[1]
            width = image[2]
            height = image[3]
            entry = occurrences.setdefault(
                xref,
                {"max_width_pt": 0.0, "max_height_pt": 0.0, "smask": smask, "width": width, "height": height},
            )
            try:
                for rect in page.get_image_rects(xref):
                    entry["max_width_pt"] = max(entry["max_width_pt"], abs(rect.width))
                    entry["max_height_pt"] = max(entry["max_height_pt"], abs(rect.height))
            except Exception:
                entry["max_width_pt"] = max(entry["max_width_pt"], width * 72 / 150)
                entry["max_height_pt"] = max(entry["max_height_pt"], height * 72 / 150)
    return occurrences


def _optimize_image(document: fitz.Document, xref: int, info: dict, settings: CompressionSettings) -> bool:
    try:
        # Le maschere di trasparenza sono oggetti PDF separati: lasciarle intatte evita
        # aloni o sfondi errati nei loghi e nelle scansioni con ritagli.
        if info.get("smask", 0) > 0:
            return False
        extracted = document.extract_image(xref)
        original = extracted.get("image", b"")
        if not original or len(original) < 12_000:
            return False
        with Image.open(io.BytesIO(original)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()

        target_width, target_height = image.size
        if settings.max_dpi > 0 and info["max_width_pt"] > 0 and info["max_height_pt"] > 0:
            target_width = min(target_width, max(1, round(info["max_width_pt"] * settings.max_dpi / 72)))
            target_height = min(target_height, max(1, round(info["max_height_pt"] * settings.max_dpi / 72)))
            scale = min(target_width / image.width, target_height / image.height, 1.0)
            target_width = max(1, round(image.width * scale))
            target_height = max(1, round(image.height * scale))
        if (target_width, target_height) != image.size:
            image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)

        has_alpha = image.mode in ("RGBA", "LA", "PA")
        buffer = io.BytesIO()
        if has_alpha:
            image.save(buffer, format="PNG", optimize=True, compress_level=9)
        else:
            if settings.grayscale:
                image = ImageOps.grayscale(image)
            elif image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(
                buffer,
                format="JPEG",
                quality=max(25, min(95, settings.jpeg_quality)),
                optimize=True,
                progressive=False,
                subsampling="4:2:0",
                dpi=(settings.max_dpi or 150, settings.max_dpi or 150),
            )
        replacement = buffer.getvalue()
        if len(replacement) >= len(original) * 0.98:
            return False
        document[0].replace_image(xref, stream=replacement)
        return True
    except Exception:
        # Un formato immagine insolito non deve impedire la compressione del resto del documento.
        return False


def _compress_raster(
    source: Path,
    destination: Path,
    settings: CompressionSettings,
    progress: ProgressCallback | None,
    cancel_event: threading.Event | None,
) -> tuple[int, int]:
    with fitz.open(source) as document:
        if document.needs_pass:
            raise CompressionError("Il PDF è protetto da password. Rimuovere la protezione e riprovare.")
        pages = document.page_count
        if pages == 0:
            raise CompressionError("Il PDF non contiene pagine.")
        output = fitz.open()
        try:
            output.set_metadata({} if settings.remove_metadata else document.metadata)
            zoom = max(72, settings.max_dpi) / 72
            matrix = fitz.Matrix(zoom, zoom)
            for index, page in enumerate(document, start=1):
                _check_cancelled(cancel_event)
                pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY if settings.grayscale else fitz.csRGB, alpha=False, annots=True)
                image_data = pixmap.tobytes("jpeg", jpg_quality=max(25, min(95, settings.jpeg_quality)))
                new_page = output.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(new_page.rect, stream=image_data)
                _notify(progress, 5 + round(index / pages * 83), f"Conversione pagina {index}/{pages}")
            output.save(destination, garbage=4, deflate=True, deflate_images=True, use_objstms=0)
        finally:
            output.close()
        return pages, pages


def _validate_pdf(path: Path, expected_pages: int) -> None:
    with fitz.open(path) as document:
        if document.needs_pass or document.page_count != expected_pages:
            raise CompressionError("La verifica del PDF prodotto non è riuscita.")
        for page in document:
            if page.rect.is_empty or page.rect.is_infinite:
                raise CompressionError("Il PDF prodotto contiene una pagina non valida.")
            page.get_pixmap(matrix=fitz.Matrix(0.15, 0.15), alpha=False)


def _notify(callback: ProgressCallback | None, percent: int, message: str) -> None:
    if callback:
        callback(max(0, min(100, percent)), message)


def _check_cancelled(event: threading.Event | None) -> None:
    if event and event.is_set():
        raise CompressionCancelled("Operazione annullata.")

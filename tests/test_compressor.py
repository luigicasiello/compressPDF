import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz
from PIL import Image

from pdf_compressor import CompressionSettings, compress_pdf, suggested_output_path


class CompressorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.source = self.folder / "input.pdf"
        document = fitz.open()
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 72), "Testo selezionabile - compatibilita portale", fontsize=16)
        image = Image.effect_noise((1400, 1000), 80).convert("RGB")
        image_path = self.folder / "photo.jpg"
        image.save(image_path, quality=98)
        page.insert_image(fitz.Rect(72, 110, 523, 432), filename=image_path)
        document.save(self.source)
        document.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_portal_profile_preserves_text_and_pages(self):
        output = self.folder / "output.pdf"
        result = compress_pdf(self.source, output, CompressionSettings(profile="portal", jpeg_quality=75, max_dpi=120))
        self.assertEqual(result.pages, 1)
        self.assertTrue(output.exists())
        with fitz.open(output) as document:
            self.assertIn("Testo selezionabile", document[0].get_text())

    def test_raster_profile_removes_text_layer(self):
        output = self.folder / "flat.pdf"
        compress_pdf(self.source, output, CompressionSettings(profile="raster", jpeg_quality=70, max_dpi=100))
        with fitz.open(output) as document:
            self.assertEqual(document.page_count, 1)
            self.assertEqual(document[0].get_text().strip(), "")

    def test_output_name_does_not_overwrite(self):
        first = suggested_output_path(self.source)
        first.touch()
        self.assertEqual(suggested_output_path(self.source).name, "input_compresso_2.pdf")


if __name__ == "__main__":
    unittest.main()

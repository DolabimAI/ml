import csv
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from vision.check import evaluate, run


class EvaluateTest(unittest.TestCase):
    def test_counts(self):
        rows = [
            {"dosya": "a", "alt_tur": "gomlek", "renk": "mavi", "tahmin_alt_tur": "gomlek",
             "en_yuksek_alt_tur": "gomlek", "tahmin_renk": "mavi", "sure_sn": 2.0},
            {"dosya": "b", "alt_tur": "kot", "renk": "lacivert", "tahmin_alt_tur": None,
             "en_yuksek_alt_tur": "kot", "tahmin_renk": "mavi", "sure_sn": 4.0},
        ]
        r = evaluate(rows)
        self.assertEqual((r["alt_tur_dogru_en_yuksek"], r["alt_tur_dogru_esik_sonrasi"], r["renk_dogru"]), (2, 1, 1))
        self.assertEqual((r["ortalama_sure_sn"], r["yanlis_renk"], r["yanlis_alt_tur"]), (3.0, ["b"], []))


class RunColorOnlyTest(unittest.TestCase):
    def test_skip_subtype_run_on_synthetic_photo(self):
        """Yalnız araç mekaniğini doğrular; sentetik fotoğraf, gerçek kontrol sonucu DEĞİL."""
        d = Path(tempfile.mkdtemp())
        Image.new("RGB", (64, 64), (200, 30, 30)).save(d / "x.png")
        with (d / "l.csv").open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["dosya", "alt_tur", "renk"], ["x.png", "tisort", "kirmizi"]])
        import vision.background as bg

        orig = bg.remove_background
        bg.remove_background = lambda img, s=None: img.convert("RGBA")  # model gerektirmeden
        try:
            rows = run(d, d / "l.csv", skip_subtype=True)
        finally:
            bg.remove_background = orig
        self.assertEqual(rows[0]["tahmin_renk"], "kirmizi")
        self.assertIn("sure_sn", rows[0])


if __name__ == "__main__":
    unittest.main()

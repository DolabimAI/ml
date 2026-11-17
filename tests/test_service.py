import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from service import codes
from service.main import create_app

ROOT = Path(__file__).resolve().parent.parent


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())

    def test_health_ok(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["codes"], {"subtypes": 35, "colors": 13, "tones": 3})

    def test_vision_module_is_mounted(self):
        self.assertIn("vision", self.client.get("/health").json()["modules"])


class CodesTest(unittest.TestCase):
    def test_counts_and_uniqueness(self):
        for values, n in ((codes.subtype_values(), 35), (codes.color_values(), 13), (codes.tone_values(), 3)):
            self.assertEqual(len(values), n)
            self.assertEqual(len(set(values)), n)

    def test_category_distribution(self):
        from collections import Counter

        counts = Counter(s["category"] for s in codes.load_codes()["subtypes"])
        self.assertEqual(
            dict(counts),
            {"ust": 8, "alt": 6, "tek_parca": 2, "dis": 7, "ayakkabi": 7, "aksesuar": 5},
        )

    def test_codes_have_no_turkish_characters(self):
        for value in codes.subtype_values() + codes.color_values() + codes.tone_values():
            self.assertTrue(value.isascii(), value)

    def test_matches_recommendation_catalog(self):
        """Ömer'in catalog.json'u ile aynı alt tür, renk ve ton kodlarını kullanıyoruz."""
        catalog = json.loads((ROOT / "recommendation" / "catalog.json").read_text(encoding="utf-8"))
        cat_sub = [s["value"] for s in catalog["subtypes"]]
        self.assertEqual(sorted(cat_sub), sorted(codes.subtype_values()))
        self.assertEqual(sorted(catalog["colors"]), sorted(codes.color_values()))
        self.assertEqual(sorted(catalog["tones"]), sorted(codes.tone_values()))


if __name__ == "__main__":
    unittest.main()

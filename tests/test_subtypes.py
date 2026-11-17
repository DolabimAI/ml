import json
import unittest
from pathlib import Path

from service import codes

ROOT = Path(__file__).resolve().parent.parent
ROWS = json.loads((ROOT / "shared" / "subtypes.json").read_text(encoding="utf-8"))["subtypes"]
BY_VALUE = {r["value"]: r for r in ROWS}
STYLES = ("gunluk", "is", "spor", "davet")


class SubtypesTest(unittest.TestCase):
    def test_35_rows_match_shared_codes(self):
        self.assertEqual([r["value"] for r in ROWS], list(codes.subtype_values()))
        for r in ROWS:
            self.assertEqual(r["category"], codes.subtype_category(r["value"]))

    def test_plan_wet_and_hot_flags(self):
        self.assertEqual({v for v, r in BY_VALUE.items() if r["avoid_when_wet"]}, {"sandalet", "terlik", "babet"})
        self.assertEqual({v for v, r in BY_VALUE.items() if r["preferred_when_wet"]}, {"yagmurluk", "mont", "bot"})
        self.assertEqual(
            {v for v, r in BY_VALUE.items() if r["preferred_when_hot"]},
            {"babet", "sandalet", "terlik", "spor_ayakkabi"},
        )

    def test_plan_example_rows(self):
        t = BY_VALUE["tisort"]
        self.assertEqual((t["styles"], t["seasons"], t["thickness"]), (["gunluk", "spor"], ["ilkbahar", "yaz"], "ince"))
        # Plan örneği mont için yalnız "gunluk" der; 7 Kasım kararıyla dış giyim tarzları geniş tutuldu
        # (Ortak Kod Listesi: gunluk, is, spor). Planın değeri bu kümenin içinde kalmalı.
        self.assertIn("gunluk", BY_VALUE["mont"]["styles"])
        self.assertEqual(BY_VALUE["mont"]["seasons"], ["kis"])
        self.assertEqual(BY_VALUE["kazak"]["thickness"], "kalin")

    def test_temperature_ranges_are_valid(self):
        for r in ROWS:
            self.assertLess(r["min_temp"], r["max_temp"], r["value"])

    def test_every_style_has_top_bottom_shoes_between_0_and_15(self):
        for t in range(0, 16):
            for style in STYLES:
                for cat in ("ust", "alt", "ayakkabi"):
                    ok = any(
                        r["category"] == cat and style in r["styles"] and r["min_temp"] <= t <= r["max_temp"]
                        for r in ROWS
                    )
                    self.assertTrue(ok, (t, style, cat))

    def test_outerwear_has_no_gap_between_minus20_and_24(self):
        for t in range(-20, 25):
            self.assertTrue(
                any(r["category"] == "dis" and r["min_temp"] <= t <= r["max_temp"] for r in ROWS), t
            )

    def test_matches_recommendation_catalog(self):
        cat = json.loads((ROOT / "recommendation" / "catalog.json").read_text(encoding="utf-8"))["subtypes"]
        self.assertEqual(sorted(cat, key=lambda r: r["value"]), sorted(ROWS, key=lambda r: r["value"]))


if __name__ == "__main__":
    unittest.main()

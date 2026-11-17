import colorsys
import unittest

import numpy as np

from service import codes
from vision.color import classify_color, classify_tone, extract_color, load_color_settings

S = load_color_settings()


def solid(h, s, v, n=400):
    r, g, b = colorsys.hsv_to_rgb(h / 360, s / 100, v / 100)
    return np.tile(np.array([[round(r * 255), round(g * 255), round(b * 255)]]), (n, 1))


class PlanExampleTest(unittest.TestCase):
    def test_plan_example_light_blue_shirt(self):
        """Plan: renk tonu 212°, doygunluk %28, parlaklık %89 -> mavi, açık."""
        self.assertEqual((classify_color(212, 28, 89, S), classify_tone(28, 89, S)), ("mavi", "acik"))
        r = extract_color(solid(212, 28, 89))
        self.assertEqual((r.color, r.tone, r.is_patterned), ("mavi", "acik", False))

    def test_ortak_kod_listesi_sample_hex(self):
        r = extract_color(np.tile(np.array([[0xA2, 0xC0, 0xE2]]), (300, 1)))
        self.assertEqual((r.color, r.tone, r.hex), ("mavi", "acik", "#A2C0E2"))


class NeutralTest(unittest.TestCase):
    def test_neutrals(self):
        cases = {
            (0, 5, 95): "beyaz", (0, 5, 10): "siyah", (0, 5, 50): "gri",
            (220, 60, 25): "lacivert", (35, 20, 85): "bej", (25, 70, 35): "kahverengi",
        }
        for hsv, expected in cases.items():
            self.assertEqual(classify_color(*hsv, S), expected, hsv)

    def test_hue_table_and_boundaries(self):
        cases = {350: "kirmizi", 5: "kirmizi", 15: "turuncu", 40: "sari", 70: "yesil",
                 170: "mavi", 250: "mor", 290: "pembe", 345: "kirmizi", 0: "kirmizi"}
        for h, expected in cases.items():
            self.assertEqual(classify_color(h, 80, 80, S), expected, h)

    def test_all_hues_return_a_valid_code(self):
        valid = set(codes.color_values())
        for h in range(0, 360):
            self.assertIn(classify_color(h, 80, 80, S), valid)

    def test_tone(self):
        self.assertEqual(classify_tone(80, 40, S), "koyu")
        self.assertEqual(classify_tone(30, 80, S), "acik")
        self.assertEqual(classify_tone(80, 80, S), "orta")


class PatternTest(unittest.TestCase):
    def test_two_colors_is_patterned(self):
        px = np.vstack([solid(212, 60, 80, 550), solid(0, 80, 80, 450)])
        r = extract_color(px)
        self.assertTrue(r.is_patterned)
        self.assertEqual(r.color, "mavi")

    def test_small_second_group_is_not_patterned(self):
        px = np.vstack([solid(212, 60, 80, 800), solid(0, 80, 80, 200)])
        self.assertFalse(extract_color(px).is_patterned)

    def test_same_color_family_is_not_patterned(self):
        px = np.vstack([solid(212, 60, 80, 600), solid(215, 62, 78, 400)])
        self.assertFalse(extract_color(px).is_patterned)

    def test_is_deterministic(self):
        rng = np.random.default_rng(1)
        px = rng.integers(0, 255, size=(2000, 3))
        self.assertEqual(extract_color(px), extract_color(px))

    def test_empty_mask_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_color(np.empty((0, 3)))


if __name__ == "__main__":
    unittest.main()

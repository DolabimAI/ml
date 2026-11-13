import itertools
import random
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from recommendation.features import (
    FEATURE_SCHEMA_VERSION, encode_outfit, encode_outfits, feature_names,
)
from recommendation.filter import Outfit, generate_candidates
from recommendation.models import Weather, load_wardrobe


ROOT = Path(__file__).resolve().parents[1]
WARDROBE = load_wardrobe(ROOT / "tests" / "sample_wardrobe.json")
BY_ID = {item.id: item for item in WARDROBE}
WEATHER = Weather(24, "yagmurlu")


def outfit(*ids: int, template: str = "ust_alt") -> Outfit:
    return Outfit(template, tuple(BY_ID[item_id] for item_id in ids))


def named_values(candidate: Outfit, weather: Weather = WEATHER, style: str = "gunluk") -> dict[str, float]:
    return dict(zip(feature_names(), encode_outfit(candidate, weather, style), strict=True))


class FeatureSchemaTests(unittest.TestCase):
    def test_v1_schema_has_unique_stable_columns(self):
        names = feature_names()
        self.assertEqual(FEATURE_SCHEMA_VERSION, "e3_v1")
        self.assertIsInstance(names, tuple)
        self.assertEqual(len(names), 126)
        self.assertEqual(len(set(names)), 126)
        # Konum sınırları katalogdan bağımsız beklenen v1 boyutlarıdır.
        self.assertEqual([names[i] for i in (0, 26, 50, 70, 95)],
                         ["ust.present", "alt.present", "tek_parca.present", "dis.present", "ayakkabi.present"])
        self.assertEqual(names[120:], ("context.style=davet", "context.style=gunluk",
                                      "context.style=is", "context.style=spor",
                                      "context.feels_like_temp", "outfit.vivid_color_count"))
        for slot in ("ust", "alt", "tek_parca", "dis", "ayakkabi"):
            for group in ("subtype", "color", "tone"):
                codes = [n.split("=", 1)[1] for n in names if n.startswith(f"{slot}.{group}=")]
                self.assertEqual(codes, sorted(codes))
        self.assertEqual(names, feature_names())

    def test_all_templates_and_outerwear_use_same_schema(self):
        candidates = (outfit(1, 9, 17), outfit(1, 9, 17, 24),
                      outfit(29, 17, template="tek_parca"), outfit(29, 17, 24, template="tek_parca"))
        for candidate in candidates:
            with self.subTest(template=candidate.template, count=len(candidate.items)):
                vector = encode_outfit(candidate, WEATHER, "gunluk")
                self.assertEqual(len(vector), 126)
                self.assertTrue(all(type(value) is float for value in vector))
                values = named_values(candidate)
                present = {i.category for i in candidate.items}
                for slot in ("ust", "alt", "tek_parca", "dis", "ayakkabi"):
                    self.assertEqual(values[f"{slot}.present"], float(slot in present))
                    if slot not in present:
                        self.assertTrue(all(v == 0 for n, v in values.items() if n.startswith(f"{slot}.")))


class FeatureValueTests(unittest.TestCase):
    def test_known_outfit_has_exact_expected_nonzero_values(self):
        # Beyaz açık tişört + lacivert koyu kot + beyaz açık spor ayakkabı.
        values = named_values(outfit(1, 9, 17))
        actual = {name: value for name, value in values.items() if value != 0}
        self.assertEqual(actual, {
            "ust.present": 1, "ust.subtype=tisort": 1, "ust.color=beyaz": 1, "ust.tone=acik": 1,
            "alt.present": 1, "alt.subtype=kot": 1, "alt.color=lacivert": 1, "alt.tone=koyu": 1,
            "ayakkabi.present": 1, "ayakkabi.subtype=spor_ayakkabi": 1,
            "ayakkabi.color=beyaz": 1, "ayakkabi.tone=acik": 1,
            "context.style=gunluk": 1, "context.feels_like_temp": 24,
        })

    def test_each_present_slot_has_one_active_code_per_group(self):
        for candidate in (outfit(3, 11, 18, 27), outfit(32, 22, 26, template="tek_parca")):
            values = named_values(candidate)
            for item in candidate.items:
                for group, expected in (("subtype", item.subtype), ("color", item.color), ("tone", item.tone)):
                    active = {n: v for n, v in values.items() if n.startswith(f"{item.category}.{group}=") and v}
                    self.assertEqual(active, {f"{item.category}.{group}={expected}": 1.0})

    def test_pattern_and_tone_are_encoded_separately(self):
        candidate = outfit(1, 9, 17)
        changed = replace(candidate, items=(replace(candidate.items[0], tone="koyu", is_patterned=True),
                                             *candidate.items[1:]))
        before, after = named_values(candidate), named_values(changed)
        differences = {n for n in before if before[n] != after[n]}
        self.assertEqual(differences, {"ust.tone=acik", "ust.tone=koyu", "ust.is_patterned"})
        self.assertEqual(after["ust.is_patterned"], 1)

    def test_context_uses_requested_style_and_raw_temperature(self):
        for style in ("gunluk", "is", "spor", "davet"):
            for temp in (-12.5, 0, 24.9, 25, 50):
                with self.subTest(style=style, temp=temp):
                    values = named_values(outfit(1, 9, 17), Weather(temp, "kapali"), style)
                    self.assertEqual(values["context.feels_like_temp"], temp)
                    self.assertEqual({n: v for n, v in values.items() if n.startswith("context.style=") and v},
                                     {f"context.style={style}": 1})

    def test_distinct_vivid_colors_include_outerwear(self):
        base = outfit(1, 9, 17, 24)
        cases = ((('siyah', 'beyaz', 'lacivert', 'bej'), 0),
                 (('kirmizi', 'kirmizi', 'mavi', 'mavi'), 2),
                 (('kirmizi', 'mavi', 'siyah', 'yesil'), 3),
                 (('kirmizi', 'sari', 'mavi', 'pembe'), 4))
        for colors, count in cases:
            candidate = replace(base, items=tuple(replace(i, color=c) for i, c in zip(base.items, colors)))
            with self.subTest(colors=colors):
                self.assertEqual(named_values(candidate)["outfit.vivid_color_count"], count)

    def test_all_six_neutral_colors_are_excluded_from_vivid_count(self):
        base = outfit(29, 17, template="tek_parca")
        for color in ("siyah", "beyaz", "gri", "bej", "lacivert", "kahverengi"):
            candidate = replace(base, items=tuple(replace(i, color=color) for i in base.items))
            self.assertEqual(named_values(candidate)["outfit.vivid_color_count"], 0)

    def test_item_order_and_ids_do_not_change_vector(self):
        base = outfit(1, 9, 17, 24)
        expected = encode_outfit(base, WEATHER, "gunluk")
        for items in itertools.permutations(base.items):
            renamed = tuple(replace(i, id=100 + j) for j, i in enumerate(items))
            self.assertEqual(encode_outfit(replace(base, items=renamed), WEATHER, "gunluk"), expected)

    def test_swapping_top_and_bottom_colors_changes_slot_features(self):
        base = outfit(1, 9, 17)
        top, bottom, shoes = base.items
        swapped = replace(base, items=(replace(top, color=bottom.color), replace(bottom, color=top.color), shoes))
        before, after = named_values(base), named_values(swapped)
        self.assertEqual({n for n in before if before[n] != after[n]},
                         {"ust.color=beyaz", "ust.color=lacivert", "alt.color=beyaz", "alt.color=lacivert"})

    def test_accessories_do_not_change_any_feature(self):
        base = outfit(1, 9, 17)
        accessory = replace(BY_ID[34], color="mor", is_patterned=True)
        changed = replace(base, items=base.items + (accessory, BY_ID[35]))
        self.assertEqual(encode_outfit(base, WEATHER, "gunluk"), encode_outfit(changed, WEATHER, "gunluk"))

    def test_history_is_encoded_without_refiltering_or_status_features(self):
        base = outfit(1, 9, 17)
        changed = replace(base, items=tuple(replace(i, status="silindi", styles=("davet",),
                                                   min_temp=-10, max_temp=-5,
                                                   avoid_when_wet=True, preferred_when_wet=False,
                                                   preferred_when_hot=False) for i in base.items))
        self.assertEqual(encode_outfit(base, WEATHER, "gunluk"), encode_outfit(changed, WEATHER, "gunluk"))

    def test_weather_condition_is_not_an_extra_feature(self):
        base = outfit(1, 9, 17)
        self.assertEqual(encode_outfit(base, WEATHER, "gunluk"),
                         encode_outfit(base, Weather(24, "gunesli"), "gunluk"))

    def test_encoding_is_repeatable_and_does_not_mutate_inputs(self):
        candidate = outfit(1, 9, 17)
        before = candidate.items
        first = encode_outfit(candidate, WEATHER, "gunluk")
        self.assertEqual(first, encode_outfit(candidate, WEATHER, "gunluk"))
        self.assertEqual(before, candidate.items)

    def test_e2_settings_and_scoring_are_not_used(self):
        candidate = outfit(1, 9, 17)
        expected = encode_outfit(candidate, WEATHER, "gunluk")
        with patch("recommendation.rule_based.RuleSettings.load", side_effect=AssertionError("E2 ayar erişimi")), \
             patch("recommendation.rule_based.score_outfit", side_effect=AssertionError("E2 puan erişimi")):
            self.assertEqual(encode_outfit(candidate, WEATHER, "gunluk"), expected)
        # Ayrı süreçte E2 modülü hiç yüklenmeden de E3 içe aktarılabilmeli.
        result = subprocess.run([sys.executable, "-c",
                                 "import sys; import recommendation.features; "
                                 "assert 'recommendation.rule_based' not in sys.modules"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class FeatureValidationTests(unittest.TestCase):
    def test_unknown_style_is_rejected_even_for_empty_batch(self):
        for action in (lambda: encode_outfit(outfit(1, 9, 17), WEATHER, "bilinmeyen"),
                       lambda: encode_outfits([], WEATHER, "bilinmeyen")):
            with self.assertRaisesRegex(ValueError, "Bilinmeyen etkinlik"):
                action()

    def test_unknown_template_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Bilinmeyen kombin şablonu"):
            encode_outfit(outfit(1, 9, 17, template="yanlis"), WEATHER, "gunluk")

    def test_missing_required_slots_are_rejected(self):
        for base in (outfit(1, 9, 17), outfit(29, 17, template="tek_parca")):
            for index in range(len(base.items)):
                candidate = replace(base, items=base.items[:index] + base.items[index + 1:])
                with self.subTest(template=base.template, removed=index), self.assertRaisesRegex(ValueError, "eksik"):
                    encode_outfit(candidate, WEATHER, "gunluk")
        with self.assertRaises(ValueError):
            encode_outfit(Outfit("ust_alt", ()), WEATHER, "gunluk")

    def test_duplicate_slot_is_rejected_including_outerwear(self):
        for candidate in (outfit(1, 2, 9, 17), outfit(1, 9, 17, 24, 25)):
            with self.assertRaisesRegex(ValueError, "Bir konumda birden fazla"):
                encode_outfit(candidate, WEATHER, "gunluk")

    def test_duplicate_id_across_different_slots_is_rejected(self):
        base = outfit(1, 9, 17)
        duplicate = replace(base, items=(base.items[0], replace(base.items[1], id=1), base.items[2]))
        with self.assertRaisesRegex(ValueError, "kimliğini"):
            encode_outfit(duplicate, WEATHER, "gunluk")

    def test_mixed_templates_are_rejected(self):
        for candidate in (outfit(1, 9, 17, 29), outfit(29, 17, 1, template="tek_parca")):
            with self.assertRaisesRegex(ValueError, "şablonuna ait olmayan"):
                encode_outfit(candidate, WEATHER, "gunluk")


class FeatureBatchTests(unittest.TestCase):
    def test_empty_batch_returns_empty_tuple(self):
        self.assertEqual(encode_outfits([], WEATHER, "gunluk"), ())

    def test_batch_matches_single_encoding_and_preserves_order(self):
        candidates = (outfit(29, 17, template="tek_parca"), outfit(1, 9, 17), outfit(3, 11, 18, 27))
        expected = tuple(encode_outfit(c, WEATHER, "gunluk") for c in candidates)
        self.assertEqual(encode_outfits(iter(candidates), WEATHER, "gunluk"), expected)
        self.assertEqual(encode_outfits(reversed(candidates), WEATHER, "gunluk"), tuple(reversed(expected)))

    def test_e1_pools_encode_without_changes(self):
        for temp, condition, style, count in ((24, "yagmurlu", "gunluk", 25),
                                               (10, "yagmurlu", "gunluk", 100),
                                               (28, "gunesli", "is", 12),
                                               (50, "gunesli", "gunluk", 0)):
            with self.subTest(temp=temp, style=style):
                weather = Weather(temp, condition)
                pool = generate_candidates(WARDROBE, weather, style, rng=random.Random(42))
                before = tuple(c.key for c in pool.candidates)
                vectors = encode_outfits(pool.candidates, weather, style)
                self.assertEqual(len(vectors), count)
                self.assertTrue(all(len(v) == 126 for v in vectors))
                self.assertEqual(tuple(c.key for c in pool.candidates), before)


class FeatureDemoTests(unittest.TestCase):
    def run_demo(self, *args):
        return subprocess.run([sys.executable, "-m", "recommendation.demo", "--method", "features", *args],
                              cwd=ROOT, text=True, capture_output=True, check=True).stdout

    def test_demo_shows_schema_dimension_and_first_candidate(self):
        output = self.run_demo()
        for expected in ("e3_v1", "Vektör boyutu: 126", "Kodlanan aday sayısı: 25",
                         "tek_parca.subtype=elbise: 1", "context.feels_like_temp: 24"):
            self.assertIn(expected, output)
        self.assertNotIn("Kural Kartı (", output)

    def test_demo_handles_empty_pool(self):
        output = self.run_demo("--temperature", "50", "--weather", "gunesli")
        self.assertIn("Kodlanan aday sayısı: 0", output)
        self.assertIn("Özellik vektörü üretilemedi: uygun aday yok.", output)


if __name__ == "__main__":
    unittest.main()

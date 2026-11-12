import itertools
import json
import random
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from recommendation.filter import Outfit, generate_candidates
from recommendation.models import Weather, load_catalog, load_wardrobe
from recommendation.rule_based import RuleSettings, score_outfit, score_pair, select_rule_outfit


ROOT = Path(__file__).resolve().parents[1]
WARDROBE = load_wardrobe(ROOT / "tests" / "sample_wardrobe.json")


def outfit(colors, id_offset=0):
    subtypes = {
        2: ("elbise", "spor_ayakkabi"),
        3: ("tisort", "kot", "spor_ayakkabi"),
        4: ("tisort", "kot", "spor_ayakkabi", "mont"),
    }[len(colors)]
    items = tuple(
        replace(next(item for item in WARDROBE if item.subtype == subtype),
                id=id_offset + index + 1, color=color)
        for index, (subtype, color) in enumerate(zip(subtypes, colors))
    )
    return Outfit("tek_parca" if len(colors) == 2 else "ust_alt", items)


class PairScoreTests(unittest.TestCase):
    def setUp(self):
        self.settings = RuleSettings.load()

    def test_all_neutrals_score_high_with_every_color(self):
        for neutral in ("siyah", "beyaz", "gri", "bej", "lacivert", "kahverengi"):
            for color in load_catalog()["colors"]:
                with self.subTest(neutral=neutral, color=color):
                    self.assertEqual(score_pair(neutral, color, self.settings), 3)
                    self.assertEqual(score_pair(color, neutral, self.settings), 3)

    def test_complete_vivid_pair_matrix(self):
        # Planın beklenen tablosu: satır/sütun sırası K, T, S, Y, M, Mor, P.
        colors = ("kirmizi", "turuncu", "sari", "yesil", "mavi", "mor", "pembe")
        expected = (
            (3, 3, 1, 2, 1, 1, 3),
            (3, 3, 3, 1, 2, 1, 1),
            (1, 3, 3, 3, 1, 2, 1),
            (2, 1, 3, 3, 3, 1, 1),
            (1, 2, 1, 3, 3, 3, 1),
            (1, 1, 2, 1, 3, 3, 3),
            (3, 1, 1, 1, 1, 3, 3),
        )
        for i, a in enumerate(colors):
            for j, b in enumerate(colors):
                with self.subTest(a=a, b=b):
                    self.assertEqual(score_pair(a, b, self.settings), expected[i][j])

    def test_project_examples_have_expected_order(self):
        self.assertEqual(score_pair("siyah", "kirmizi", self.settings), 3)
        self.assertEqual(score_pair("mavi", "mavi", self.settings), 3)
        self.assertEqual(score_pair("mavi", "yesil", self.settings), 3)
        self.assertEqual(score_pair("mavi", "turuncu", self.settings), 2)
        self.assertEqual(score_pair("kirmizi", "mor", self.settings), 1)

    def test_unknown_color_is_not_silently_scored(self):
        for pair in (("bordo", "mavi"), ("siyah", "MAVI"), ("mavi", "")):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                score_pair(*pair, self.settings)


class OutfitScoreTests(unittest.TestCase):
    def setUp(self):
        self.settings = RuleSettings.load()

    def test_same_color_different_tones_scores_high(self):
        candidate = outfit(("mavi", "mavi"))
        candidate = replace(candidate, items=(replace(candidate.items[0], tone="acik"),
                                              replace(candidate.items[1], tone="koyu")))
        score = score_outfit(candidate, self.settings)
        self.assertEqual(score.pair_average, 3)
        self.assertEqual(score.vivid_color_count, 1)
        self.assertEqual(score.penalty, 0)
        self.assertEqual(score.total, 3)

    def test_pair_average_not_sum_for_different_template_sizes(self):
        for colors in (("siyah", "beyaz"), ("siyah", "beyaz", "gri"),
                       ("siyah", "beyaz", "gri", "bej")):
            with self.subTest(colors=colors):
                score = score_outfit(outfit(colors), self.settings)
                self.assertEqual(score.pair_average, 3)
                self.assertEqual(score.vivid_color_count, 0)
                self.assertEqual(score.total, 3)

    def test_complementary_pair_and_neutral_average(self):
        score = score_outfit(outfit(("mavi", "turuncu", "siyah")), self.settings)
        self.assertAlmostEqual(score.pair_average, 8 / 3)
        self.assertEqual(score.penalty, 0)
        self.assertAlmostEqual(score.total, 8 / 3)

    def test_three_distinct_vivid_colors_receive_penalty(self):
        score = score_outfit(outfit(("kirmizi", "mavi", "mor")), self.settings)
        self.assertAlmostEqual(score.pair_average, 5 / 3)
        self.assertEqual(score.vivid_color_count, 3)
        self.assertEqual(score.penalty, 0.5)
        self.assertAlmostEqual(score.total, 7 / 6)

    def test_four_distinct_vivid_colors_receive_two_penalties(self):
        score = score_outfit(outfit(("kirmizi", "sari", "mavi", "pembe")), self.settings)
        self.assertAlmostEqual(score.pair_average, 4 / 3)
        self.assertEqual(score.vivid_color_count, 4)
        self.assertEqual(score.penalty, 1)
        self.assertAlmostEqual(score.total, 1 / 3)

    def test_repeated_colors_do_not_add_penalty(self):
        score = score_outfit(outfit(("kirmizi", "kirmizi", "mavi", "mavi")), self.settings)
        self.assertEqual(score.vivid_color_count, 2)
        self.assertEqual(score.penalty, 0)
        self.assertAlmostEqual(score.total, 5 / 3)

    def test_outerwear_participates_in_average_and_color_count(self):
        score = score_outfit(outfit(("mavi", "turuncu", "siyah", "yesil")), self.settings)
        self.assertEqual(score.pair_average, 2.5)
        self.assertEqual(score.vivid_color_count, 3)
        self.assertEqual(score.penalty, 0.5)
        self.assertEqual(score.total, 2)

    def test_accessories_do_not_change_score(self):
        candidate = outfit(("mavi", "turuncu", "siyah"))
        accessory = replace(next(i for i in WARDROBE if i.category == "aksesuar"),
                            id=100, color="yesil")
        with_accessory = replace(candidate, items=candidate.items + (accessory,))
        self.assertEqual(score_outfit(candidate, self.settings), score_outfit(with_accessory, self.settings))

    def test_item_order_does_not_change_score(self):
        candidate = outfit(("mavi", "turuncu", "siyah", "yesil"))
        for items in itertools.permutations(candidate.items):
            with self.subTest(ids=[i.id for i in items]):
                self.assertEqual(score_outfit(candidate, self.settings),
                                 score_outfit(replace(candidate, items=items), self.settings))

    def test_tone_and_pattern_have_no_extra_weight(self):
        candidate = outfit(("mavi", "turuncu", "siyah"))
        changed = replace(candidate, items=tuple(replace(i, tone="koyu", is_patterned=True)
                                                for i in candidate.items))
        self.assertEqual(score_outfit(candidate, self.settings), score_outfit(changed, self.settings))

    def test_penalty_is_configurable(self):
        score = score_outfit(outfit(("kirmizi", "mavi", "mor")),
                             replace(self.settings, extra_color_penalty=0.25))
        self.assertEqual(score.penalty, 0.25)
        self.assertAlmostEqual(score.total, 5 / 3 - 0.25)

    def test_final_score_never_becomes_negative(self):
        score = score_outfit(outfit(("kirmizi", "mavi", "mor")),
                             replace(self.settings, extra_color_penalty=10))
        self.assertEqual(score.penalty, 10)
        self.assertEqual(score.total, 0)

    def test_too_few_main_items_are_rejected(self):
        base = outfit(("mavi", "siyah"))
        accessory = next(i for i in WARDROBE if i.category == "aksesuar")
        for items in ((), base.items[:1], base.items[:1] + (accessory,)):
            with self.subTest(items=items), self.assertRaises(ValueError):
                score_outfit(replace(base, items=items), self.settings)

    def test_duplicate_main_item_is_rejected(self):
        base = outfit(("mavi", "siyah"))
        with self.assertRaises(ValueError):
            score_outfit(replace(base, items=(base.items[0], base.items[0])), self.settings)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = RuleSettings.load()

    def test_empty_candidates_return_none(self):
        self.assertIsNone(select_rule_outfit([], settings=self.settings))

    def test_single_candidate_is_returned_with_its_score(self):
        candidate = outfit(("mavi", "turuncu", "siyah"))
        result = select_rule_outfit([candidate], settings=self.settings)
        assert result is not None, "Dolu aday havuzundan kart seçilmeli"
        self.assertIs(result.outfit, candidate)
        self.assertAlmostEqual(result.score.total, 8 / 3)
        self.assertEqual(result.tied_best_count, 1)

    def test_highest_score_wins_regardless_of_input_order(self):
        low = outfit(("kirmizi", "mavi", "mor"))
        middle = outfit(("mavi", "turuncu", "siyah"), 10)
        high = outfit(("siyah", "beyaz", "gri"), 20)
        for candidates in itertools.permutations((low, middle, high)):
            result = select_rule_outfit(iter(candidates), settings=self.settings, rng=random.Random(42))
            assert result is not None, "Dolu aday havuzundan kart seçilmeli"
            self.assertIs(result.outfit, high)
            self.assertEqual(result.score.total, 3)

    def test_ties_include_all_best_candidates_and_exclude_lower_scores(self):
        low = outfit(("kirmizi", "mavi", "mor"))
        first = outfit(("siyah", "beyaz", "gri"), 10)
        second = outfit(("mavi", "mavi", "mavi"), 20)
        chosen = set()
        for seed in range(20):
            result = select_rule_outfit([first, low, second], settings=self.settings, rng=random.Random(seed))
            assert result is not None, "Eşit puanlı adaylar arasından kart seçilmeli"
            self.assertEqual(result.tied_best_count, 2)
            self.assertEqual(result.score.total, 3)
            chosen.add(result.outfit.key)
        self.assertEqual(chosen, {first.key, second.key})

    def test_fixed_seed_repeats_tie_choice(self):
        candidates = [outfit(("siyah", "beyaz")), outfit(("mavi", "mavi"), 10)]
        a = select_rule_outfit(candidates, rng=random.Random(42))
        b = select_rule_outfit(candidates, rng=random.Random(42))
        assert a is not None and b is not None, "Her iki çağrıda da kart seçilmeli"
        self.assertEqual(a, b)

    def test_selection_does_not_round_scores(self):
        settings = replace(self.settings, high_score=3, medium_score=2.9998, low_score=2.9996)
        high = outfit(("siyah", "beyaz", "gri"))
        lower = outfit(("kirmizi", "mavi", "siyah"), 10)
        result = select_rule_outfit([lower, high], settings=settings, rng=random.Random(42))
        assert result is not None, "Dolu aday havuzundan kart seçilmeli"
        self.assertIs(result.outfit, high)
        self.assertEqual(result.tied_best_count, 1)

    def test_e1_candidates_are_preserved_and_selected_card_belongs_to_pool(self):
        scenarios = ((24, "yagmurlu", "gunluk", 25), (10, "yagmurlu", "gunluk", 100),
                     (28, "gunesli", "is", 12), (6, "karli", "gunluk", 100))
        for temp, weather, style, count in scenarios:
            with self.subTest(temp=temp, weather=weather, style=style):
                pool = generate_candidates(WARDROBE, Weather(temp, weather), style, rng=random.Random(42))
                before = tuple(c.key for c in pool.candidates)
                result = select_rule_outfit(pool.candidates, settings=self.settings, rng=random.Random(42))
                assert result is not None, "Bu E1 senaryosunda uygun kart bulunmalı"
                self.assertEqual(len(pool.candidates), count)
                self.assertIn(result.outfit, pool.candidates)
                # Bu örnek dolapta her bağlamda 3 puanlı nötr kombin mevcut.
                self.assertEqual(result.score.total, 3)
                self.assertEqual(tuple(c.key for c in pool.candidates), before)

    def test_rejected_outfit_cannot_be_selected(self):
        context = Weather(24, "yagmurlu")
        pool = generate_candidates(WARDROBE, context, "gunluk", rng=random.Random(42))
        first = select_rule_outfit(pool.candidates, rng=random.Random(42))
        assert first is not None, "Ret uygulanmadan önce kart seçilmeli"
        updated = generate_candidates(WARDROBE, context, "gunluk", rejected_outfits=[first.outfit.key],
                                      rng=random.Random(42))
        result = select_rule_outfit(updated.candidates, rng=random.Random(42))
        assert result is not None, "Ret sonrası kalan adaylardan kart seçilmeli"
        self.assertNotEqual(result.outfit.key, first.outfit.key)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.settings = RuleSettings.load()

    def test_settings_file_can_change_scores(self):
        data = json.loads((ROOT / "recommendation" / "rule_settings.json").read_text())
        data["high_score"] = 5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            settings = RuleSettings.load(path)
        self.assertEqual(score_pair("siyah", "mavi", settings), 5)

    def test_unknown_missing_duplicate_and_overlapping_colors_are_rejected(self):
        changes = (
            {"neutral_colors": self.settings.neutral_colors + ("bordo",)},
            {"neutral_colors": self.settings.neutral_colors[:-1]},
            {"color_wheel": self.settings.color_wheel + ("mavi",)},
            {"neutral_colors": self.settings.neutral_colors + ("mavi",)},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.settings, **change)

    def test_ambiguous_or_invalid_complementary_pairs_are_rejected(self):
        for pairs in ((("mavi", "yesil"),), (("mavi", "mavi"),), (("siyah", "mavi"),),
                      (("mavi", "bordo"),), (("mavi", "turuncu"), ("turuncu", "mavi"))):
            with self.subTest(pairs=pairs), self.assertRaises(ValueError):
                replace(self.settings, complementary_pairs=pairs)

    def test_invalid_numeric_settings_are_rejected(self):
        changes = ({"high_score": 2}, {"low_score": -1}, {"medium_score": 4},
                   {"high_score": float("nan")}, {"extra_color_penalty": float("inf")},
                   {"extra_color_penalty": -0.1}, {"high_score": True})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.settings, **change)

    def test_bad_settings_file_structure_is_rejected(self):
        original = json.loads((ROOT / "recommendation" / "rule_settings.json").read_text())
        invalid = ([], {}, {**original, "color_wheel": "mavi"},
                   {**original, "extra": 1}, {**original, "complementary_pairs": ["mavi"]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            for data in invalid:
                with self.subTest(data=data), self.assertRaises(ValueError):
                    path.write_text(json.dumps(data), encoding="utf-8")
                    RuleSettings.load(path)


class DemoTests(unittest.TestCase):
    def run_demo(self, *args):
        return subprocess.run([sys.executable, "-m", "recommendation.demo", *args], cwd=ROOT,
                              text=True, capture_output=True, check=True).stdout

    def test_default_demo_stays_candidate_only(self):
        output = self.run_demo()
        self.assertIn("Aday sayısı: 25", output)
        self.assertNotIn("Kural Kartı", output)

    def test_rule_demo_shows_card_and_score_breakdown(self):
        output = self.run_demo("--method", "rule")
        self.assertIn("Aday sayısı: 25", output)
        self.assertIn("Kural Kartı (", output)
        self.assertIn("Çift puanı ortalaması: 3.000", output)
        self.assertIn("Kural puanı: 3.000", output)

    def test_rule_demo_handles_empty_pool(self):
        output = self.run_demo("--method", "rule", "--temperature", "50", "--weather", "gunesli")
        self.assertIn("Aday sayısı: 0", output)
        self.assertIn("Kural Kartı üretilemedi: uygun aday yok.", output)


if __name__ == "__main__":
    unittest.main()

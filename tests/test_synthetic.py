import csv
import json
import random
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from recommendation import synthetic
from recommendation.filter import Outfit, generate_candidates
from recommendation.history import LEARNING_KEYS
from recommendation.models import Weather, load_wardrobe
from recommendation.synthetic import (
    CurvePoint, SimulatedDecision, SyntheticSettings, crossover_point, decide,
    learning_curve, load_profiles, plot_learning_curve, simulate_user, write_curve_csv,
)


ROOT = Path(__file__).resolve().parents[1]
WARDROBE = load_wardrobe(ROOT / "tests" / "sample_wardrobe.json")
ITEMS = {i.id: i for i in WARDROBE}
DARK = Outfit("ust_alt", tuple(ITEMS[i] for i in (2, 9, 19)))    # siyah, lacivert, kahverengi; hepsi koyu
LIGHT = Outfit("ust_alt", tuple(ITEMS[i] for i in (1, 10, 17)))  # beyaz/mavi; hepsi açık
MIXED = Outfit("ust_alt", tuple(ITEMS[i] for i in (2, 9, 17)))   # iki koyu nötr + beyaz açık
PROFILE = load_profiles()["notr_koyu"]
SMALL = replace(SyntheticSettings.load(), decision_count=20, run_count=1)


def decision(index, key, mode="model"):
    return SimulatedDecision(index, Weather(10, "kapali"), "gunluk", 1, key, mode, 0.0, 0.0)


def point(n, learned, rule):
    return CurvePoint(n, learned, learned, learned, rule, 0.0, 0.0, 0.0)


class ProfileTests(unittest.TestCase):
    def test_shipped_profile_is_neutral_and_dark(self):
        self.assertEqual(PROFILE.liked_tones, ("koyu",))
        self.assertEqual(set(PROFILE.liked_colors or ()),
                         {"siyah", "beyaz", "gri", "bej", "lacivert", "kahverengi"})
        self.assertIsNone(PROFILE.liked_patterned)

    def test_utility_is_share_of_matching_main_items(self):
        self.assertEqual(PROFILE.utility(DARK), 1.0)
        self.assertEqual(PROFILE.utility(LIGHT), 0.0)
        self.assertAlmostEqual(PROFILE.utility(MIXED), 2 / 3)

    def test_accessories_do_not_change_utility(self):
        with_accessory = Outfit("ust_alt", DARK.items + (ITEMS[35],))  # beyaz açık şapka
        self.assertEqual(PROFILE.utility(with_accessory), 1.0)

    def test_invalid_profiles_are_rejected(self):
        bad = (dict(liked_colors=("tshirt",)), dict(liked_tones=("dark",)),
               dict(liked_colors=None, liked_tones=None, liked_patterned=None),
               dict(accept_threshold=1.5), dict(accept_threshold=True), dict(liked_patterned="evet"),
               dict(profile_id=" "), dict(liked_colors=("siyah", "siyah")))
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(PROFILE, **change)

    def test_profile_file_rejects_unknown_fields(self):
        row = {"description": "x", "liked_colors": None, "liked_tones": ["koyu"],
               "liked_patterned": None, "accept_threshold": 0.5, "extra": 1}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(json.dumps({"x": row}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_profiles(path)


class DecideTests(unittest.TestCase):
    def test_higher_utility_card_is_chosen(self):
        rng = random.Random(42)
        self.assertEqual(decide(PROFILE, DARK, LIGHT, rng), "KT")
        self.assertEqual(decide(PROFILE, LIGHT, DARK, rng), "OT")
        self.assertEqual(decide(PROFILE, MIXED, DARK, rng), "OT")

    def test_both_below_threshold_is_neither(self):
        other_light = Outfit("ust_alt", tuple(ITEMS[i] for i in (1, 10, 22)))  # beyaz terlik, açık
        self.assertEqual(decide(PROFILE, LIGHT, other_light, random.Random(1)), "HB")
        self.assertEqual(decide(PROFILE, MIXED, LIGHT, random.Random(1)), "KT")  # 2/3 eşiği geçer

    def test_same_main_outfit_is_single_card_without_learning(self):
        self.assertEqual(decide(PROFILE, DARK, DARK, random.Random(1)), "AT")
        self.assertEqual(decide(PROFILE, LIGHT, LIGHT, random.Random(1)), "AR")
        self.assertNotIn("AT", LEARNING_KEYS)
        self.assertNotIn("AR", LEARNING_KEYS)

    def test_equal_utility_tie_is_seeded_and_uses_both_cards(self):
        other_dark = Outfit("ust_alt", tuple(ITEMS[i] for i in (2, 16, 19)))
        picks = {decide(PROFILE, DARK, other_dark, random.Random(seed)) for seed in range(30)}
        self.assertEqual(picks, {"KT", "OT"})
        self.assertEqual(decide(PROFILE, DARK, other_dark, random.Random(7)),
                         decide(PROFILE, DARK, other_dark, random.Random(7)))


class SettingsTests(unittest.TestCase):
    def test_shipped_settings_load(self):
        settings = SyntheticSettings.load()
        self.assertEqual((settings.decision_count, settings.run_count, settings.window), (50, 20, 10))
        self.assertTrue(all(0 <= t <= 15 for t in settings.temperatures))

    def test_invalid_settings_are_rejected(self):
        bad = (dict(conditions=("yagmur",)), dict(style_weights=(("gunluk", 0.0),)),
               dict(style_weights=(("parti", 1.0),)), dict(window=0), dict(temperatures=()),
               dict(decision_count=True))
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(SMALL, **change)

    def test_settings_file_requires_all_fields(self):
        data = json.loads((ROOT / "recommendation" / "synthetic_settings.json").read_text(encoding="utf-8"))
        del data["window"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                SyntheticSettings.load(path)


class SimulationTests(unittest.TestCase):
    def test_same_run_index_reproduces_and_other_run_differs(self):
        first = simulate_user(PROFILE, WARDROBE, SMALL, run_index=0)
        self.assertEqual(first, simulate_user(PROFILE, WARDROBE, SMALL, run_index=0))
        self.assertNotEqual(first, simulate_user(PROFILE, WARDROBE, SMALL, run_index=1))
        self.assertEqual(len(first), SMALL.decision_count)

    def test_both_cards_come_from_one_shared_e1_pool(self):
        pools, seen = [], []

        def record_pool(*args, **kwargs):
            pools.append(generate_candidates(*args, **kwargs))
            return pools[-1]

        real_rule, real_learned = synthetic.select_rule_outfit, synthetic.select_learned_outfit

        def rule(candidates, **kwargs):
            seen.append(("kural", candidates))
            return real_rule(candidates, **kwargs)

        def learned(candidates, *args, **kwargs):
            seen.append(("ogrenen", candidates))
            return real_learned(candidates, *args, **kwargs)

        with patch.object(synthetic, "generate_candidates", side_effect=record_pool), \
                patch.object(synthetic, "select_rule_outfit", side_effect=rule), \
                patch.object(synthetic, "select_learned_outfit", side_effect=learned):
            simulate_user(PROFILE, WARDROBE, SMALL)
        used = [p for p in pools if p.candidates]
        self.assertEqual(len(used), SMALL.decision_count)
        for i, pool in enumerate(used):
            self.assertIs(seen[2 * i][1], pool.candidates)
            self.assertIs(seen[2 * i + 1][1], pool.candidates)

    def test_cold_start_follows_learning_decision_count(self):
        decisions = simulate_user(PROFILE, WARDROBE, replace(SMALL, decision_count=25))
        learned_so_far = 0
        for d in decisions:
            if learned_so_far < 10:
                self.assertEqual(d.ogrenen_mode, "soguk_baslangic", d.index)
            else:
                self.assertIn(d.ogrenen_mode, ("model", "kesif"), d.index)
            learned_so_far += d.result_key in LEARNING_KEYS

    def test_only_profile_result_codes_are_produced(self):
        decisions = simulate_user(PROFILE, WARDROBE, SMALL)
        self.assertLessEqual({d.result_key for d in decisions}, {"KT", "OT", "HB", "AT", "AR"})


class CurveTests(unittest.TestCase):
    def test_trailing_window_shares(self):
        run = (decision(1, "OT"), decision(2, "KT"), decision(3, "HB"), decision(4, "AT"), decision(5, "AR"))
        curve = learning_curve([run], window=2)
        self.assertEqual([p.learned_rate for p in curve], [1.0, 0.5, 0.0, 0.0, 0.0])
        self.assertEqual([p.rule_rate for p in curve], [0.0, 0.5, 0.5, 0.0, 0.0])
        self.assertEqual([p.neither_rate for p in curve], [0.0, 0.0, 0.5, 0.5, 0.0])
        self.assertEqual([p.same_rate for p in curve], [0.0, 0.0, 0.0, 0.5, 1.0])  # AR de tek kart

    def test_runs_are_averaged_with_quartiles(self):
        runs = [(decision(1, "OT"),), (decision(1, "KT"),)]
        (p,) = learning_curve(runs, window=10)
        self.assertEqual((p.learned_rate, p.rule_rate), (0.5, 0.5))
        self.assertEqual((p.learned_q1, p.learned_q3), (0.25, 0.75))

    def test_unequal_runs_are_rejected(self):
        with self.assertRaises(ValueError):
            learning_curve([(decision(1, "OT"),), ()], window=2)

    def test_crossover_requires_learned_lead_until_end(self):
        curve = [point(1, 0.6, 0.3), point(2, 0.2, 0.5), point(3, 0.6, 0.3), point(4, 0.7, 0.2)]
        self.assertEqual(crossover_point(curve), 3)
        self.assertIsNone(crossover_point(curve + [point(5, 0.4, 0.4)]))


class T37SyntheticLearningTests(unittest.TestCase):
    """T-37: sentetik profilde model 30 karar içinde tercihi yakalıyor ve grafik çıkıyor."""

    @classmethod
    def setUpClass(cls):
        settings = replace(SyntheticSettings.load(), run_count=10, decision_count=40)
        cls.runs = [simulate_user(PROFILE, WARDROBE, settings, run_index=i) for i in range(settings.run_count)]
        cls.curve = learning_curve(cls.runs, settings.window)

    def test_t37_learned_card_leads_within_30_decisions(self):
        crossover = crossover_point(self.curve)
        self.assertIsNotNone(crossover)
        assert crossover is not None
        self.assertLessEqual(crossover, 30)
        self.assertGreater(self.curve[-1].learned_rate, 2 * self.curve[-1].rule_rate)

    def test_t37_plot_and_csv_are_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            png, table = Path(tmp) / "e10.png", Path(tmp) / "e10.csv"
            plot_learning_curve(self.curve, PROFILE, png, run_count=len(self.runs), window=10,
                                crossover=crossover_point(self.curve), cold_start_end=11)
            write_curve_csv(self.curve, table)
            self.assertEqual(png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            with table.open(encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
        self.assertEqual(rows[0][:2], ["karsilastirma", "ogrenen_orani"])
        self.assertEqual(len(rows), 41)

    def test_t37_cli_marks_results_as_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-m", "recommendation.synthetic", "--runs", "2", "--decisions", "15",
                 "--output-dir", tmp], cwd=ROOT, capture_output=True, text=True, check=True)
            self.assertTrue((Path(tmp) / "E10-notr_koyu.png").exists())
        self.assertIn("SENTETİK TEST", result.stdout)
        self.assertIn("Kesişme:", result.stdout)


if __name__ == "__main__":
    unittest.main()

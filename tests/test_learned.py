import json
import random
import subprocess
import sys
import tempfile
import unittest
import warnings
from contextlib import chdir
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from sklearn.exceptions import ConvergenceWarning

from recommendation.features import encode_outfit, feature_names
from recommendation.filter import Outfit, generate_candidates
from recommendation.history import ComparisonDecision, build_training_data, load_history
from recommendation.learned import LearnedSettings, _make_pipeline, select_learned_outfit
from recommendation.models import Weather, load_wardrobe


ROOT = Path(__file__).resolve().parents[1]
WARDROBE = load_wardrobe(ROOT / "tests" / "sample_wardrobe.json")
ITEMS = {i.id: i for i in WARDROBE}
LIGHT = Outfit("ust_alt", tuple(ITEMS[i] for i in (1, 9, 17)))
DARK = Outfit("ust_alt", tuple(ITEMS[i] for i in (2, 9, 17)))
WEATHER = Weather(24, "yagmurlu")


def history(count=10, key="KT", user_id="demo", reverse=False):
    rule, learned = (DARK, LIGHT) if reverse else (LIGHT, DARK)
    return tuple(ComparisonDecision(user_id, f"h{i:03}", key,
                                   datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=i),
                                   WEATHER, "gunluk", rule, learned) for i in range(count))


def select(records=(), candidates=(LIGHT, DARK), settings=None, rng=None, **kwargs):
    return select_learned_outfit(candidates, kwargs.pop("weather", WEATHER), "gunluk", records,
                                 user_id=kwargs.pop("user_id", "demo"),
                                 settings=settings or LearnedSettings(), rng=rng or random.Random(42), **kwargs)


class LearnedModeTests(unittest.TestCase):
    def test_empty_pool_does_not_train(self):
        with patch("recommendation.learned._make_pipeline", side_effect=AssertionError("Eğitim yapılmamalı")):
            self.assertIsNone(select(history(), candidates=()))

    def test_zero_and_nine_decisions_do_not_train(self):
        with patch("recommendation.learned._make_pipeline", side_effect=AssertionError("Eğitim yapılmamalı")):
            for count in (0, 9):
                result = select(history(count))
                assert result is not None
                self.assertEqual((result.ogrenen_mode, result.reason), ("soguk_baslangic", "yetersiz_karar"))
                self.assertEqual(result.decision_count, count)
                self.assertEqual(result.positive_count + result.negative_count, count * 2)
                self.assertIsNone(result.probability)

    def test_ten_and_eleven_decisions_can_train(self):
        for count in (10, 11):
            result = select(history(count))
            assert result is not None
            self.assertEqual(result.ogrenen_mode, "model")
            self.assertEqual(result.rule_decision_count, count)
            self.assertEqual(result.positive_count, 10)
            self.assertIsNone(result.reason)

    def test_only_negative_examples_fall_back_without_training(self):
        with patch("recommendation.learned._make_pipeline", side_effect=AssertionError("Tek sınıf")):
            for key in ("KR", "OR", "HB"):
                result = select(history(12, key))
                assert result is not None
                self.assertEqual((result.ogrenen_mode, result.reason), ("soguk_baslangic", "tek_sinif"))
                self.assertEqual(result.positive_count, 0)

    def test_only_positive_examples_fall_back_without_training(self):
        with patch("recommendation.learned._make_pipeline", side_effect=AssertionError("Tek sınıf")):
            result = select(history(12, "OT"), settings=LearnedSettings(rule_learning_limit=0))
        assert result is not None
        self.assertEqual(result.reason, "tek_sinif")
        self.assertEqual((result.positive_count, result.negative_count), (12, 0))

    def test_no_examples_with_zero_cold_limit_has_explicit_reason(self):
        result = select(settings=LearnedSettings(cold_start_limit=0))
        assert result is not None
        self.assertEqual((result.ogrenen_mode, result.reason), ("soguk_baslangic", "ornek_yok"))

    def test_same_clean_result_type_still_produces_two_classes(self):
        result = select(history(10, "OT"))
        assert result is not None
        self.assertEqual(result.ogrenen_mode, "model")
        self.assertEqual((result.positive_count, result.negative_count), (10, 10))

    def test_exploration_boundary_is_strict_and_training_happens_first(self):
        for draw, expected in ((0.099999, "kesif"), (0.10, "model")):
            rng = Mock(spec=random.Random)
            rng.random.return_value = draw
            rng.choice.side_effect = lambda candidates: candidates[0]
            with patch("recommendation.learned._make_pipeline", wraps=_make_pipeline) as factory:
                result = select(history(), rng=rng)
                assert result is not None
                self.assertEqual(result.ogrenen_mode, expected)
                factory.assert_called_once()
                if expected == "kesif":
                    self.assertIsNone(result.probability)

    def test_seed_reproduces_all_selection_modes(self):
        for records, seed in (((), 42), (history(), 42), (history(), 31)):
            self.assertEqual(select(records, rng=random.Random(seed)), select(records, rng=random.Random(seed)))

    def test_configurable_exploration_endpoints(self):
        for rate, expected in ((0, "model"), (1, "kesif")):
            result = select(history(), settings=LearnedSettings(exploration_rate=rate))
            assert result is not None
            self.assertEqual(result.ogrenen_mode, expected)

    def test_seeded_many_draws_are_approximately_ten_percent(self):
        model = Mock()
        model.classes_ = np.array([0, 1])
        model.predict_proba.return_value = np.array([[0.1, 0.9], [0.8, 0.2]])
        rng = random.Random(42)
        count = 0
        records = history()
        with patch("recommendation.learned._make_pipeline", return_value=model):
            for _ in range(1000):
                result = select(records, rng=rng)
                assert result is not None
                count += result.ogrenen_mode == "kesif"
        self.assertTrue(70 <= count <= 130, count)
        self.assertEqual(model.fit.call_count, 1000)


class LearnedModelTests(unittest.TestCase):
    def test_real_model_learns_simple_preference_with_unseen_item_ids(self):
        candidates = tuple(replace(c, items=tuple(replace(i, id=i.id + 100) for i in c.items)) for c in (LIGHT, DARK))
        result = select(history(), candidates=candidates)
        assert result is not None and result.probability is not None
        self.assertEqual(result.outfit, candidates[0])
        self.assertGreater(result.probability, 0.5)
        self.assertLessEqual(result.probability, 1)

    def test_opposite_users_do_not_share_model_state(self):
        first = select(history(user_id="one"), user_id="one")
        second = select(history(user_id="two", reverse=True), user_id="two")
        again = select(history(user_id="one"), user_id="one")
        assert first is not None and second is not None
        self.assertEqual(first.outfit, LIGHT)
        self.assertEqual(second.outfit, DARK)
        self.assertEqual(first, again)
        with self.assertRaisesRegex(ValueError, "başka kullanıcı"):
            select(history(user_id="two"), user_id="one")

    def test_every_eligible_call_creates_and_fits_a_fresh_pipeline(self):
        pipelines = []

        def factory(settings):
            model = _make_pipeline(settings)
            pipelines.append(model)
            return model

        with patch("recommendation.learned._make_pipeline", side_effect=factory):
            select(history())
            select(history(reverse=True), settings=LearnedSettings(exploration_rate=1))
        self.assertEqual(len(pipelines), 2)
        self.assertIsNot(pipelines[0], pipelines[1])
        for model in pipelines:
            self.assertTrue(hasattr(model.named_steps["classifier"], "coef_"))

    def test_scaler_uses_only_history_and_keeps_other_features(self):
        records = tuple(replace(row, weather=Weather(10 + i, "kapali")) for i, row in enumerate(history()))
        pipeline = _make_pipeline(LearnedSettings())
        with patch("recommendation.learned._make_pipeline", return_value=pipeline):
            select(records, weather=Weather(50, "gunesli"))
        preprocess = pipeline.named_steps["preprocess"]
        scaler = preprocess.named_transformers_["numeric"]
        self.assertEqual(scaler.n_samples_seen_, 20)
        np.testing.assert_allclose(scaler.mean_, [14.5, 0])
        vector = encode_outfit(LIGHT, WEATHER, "gunluk")
        transformed = preprocess.transform([vector])
        numeric = {feature_names().index("context.feels_like_temp"), feature_names().index("outfit.vivid_color_count")}
        np.testing.assert_array_equal(transformed[0, 2:], [v for i, v in enumerate(vector) if i not in numeric])
        self.assertEqual(transformed.shape, (1, 126))

    def test_positive_class_column_is_looked_up(self):
        model = Mock()
        model.classes_ = np.array([1, 0])
        model.predict_proba.return_value = np.array([[0.2, 0.8], [0.9, 0.1]])
        with patch("recommendation.learned._make_pipeline", return_value=model):
            result = select(history())
        assert result is not None
        self.assertEqual((result.outfit, result.probability), (DARK, 0.9))

    def test_exact_ties_choose_only_best_without_rounding(self):
        extra = Outfit("ust_alt", tuple(ITEMS[i] for i in (7, 9, 17)))
        model = Mock()
        model.classes_ = np.array([0, 1])
        model.predict_proba.return_value = np.array([[0.1, 0.9], [0.1, 0.9], [0.10001, 0.89999]])
        choices = set()
        with patch("recommendation.learned._make_pipeline", return_value=model):
            for seed in range(20):
                result = select(history(), candidates=(LIGHT, DARK, extra),
                                settings=LearnedSettings(exploration_rate=0), rng=random.Random(seed))
                assert result is not None
                choices.add(result.outfit.key)
        self.assertEqual(choices, {LIGHT.key, DARK.key})

    def test_training_failure_is_not_hidden_by_exploration(self):
        model = Mock()
        model.fit.side_effect = ValueError("training failed")
        with patch("recommendation.learned._make_pipeline", return_value=model):
            with self.assertRaisesRegex(ValueError, "training failed"):
                select(history(), settings=LearnedSettings(exploration_rate=1))

    def test_convergence_warning_is_an_explicit_error(self):
        model = Mock()

        def fail(*args):
            warnings.warn("not converged", ConvergenceWarning)

        model.fit.side_effect = fail
        with patch("recommendation.learned._make_pipeline", return_value=model):
            with self.assertRaisesRegex(RuntimeError, "yakınsamadı"):
                select(history())

    def test_invalid_probability_is_rejected(self):
        for value in (float("nan"), float("inf"), -0.1, 1.1):
            model = Mock()
            model.classes_ = np.array([0, 1])
            model.predict_proba.return_value = np.array([[0.1, value], [0.8, 0.2]])
            with patch("recommendation.learned._make_pipeline", return_value=model), self.assertRaises(RuntimeError):
                select(history())

    def test_e1_pool_and_history_are_unchanged_and_card_is_from_pool(self):
        pool = generate_candidates(WARDROBE, WEATHER, "gunluk", rng=random.Random(42))
        before = pool.candidates
        records = history()
        result = select(records, candidates=iter(pool.candidates))
        assert result is not None
        self.assertIn(result.outfit, before)
        self.assertEqual(pool.candidates, before)
        self.assertEqual(records, history())

    def test_no_model_files_are_written(self):
        with tempfile.TemporaryDirectory() as directory, chdir(directory):
            select(history())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_candidate_is_rejected_even_during_cold_start(self):
        with self.assertRaises(ValueError):
            select(candidates=(Outfit("ust_alt", ()),))


class LearnedSettingsTests(unittest.TestCase):
    def test_file_defaults_match_declared_defaults(self):
        self.assertEqual(LearnedSettings.load(), LearnedSettings())

    def test_invalid_settings_are_rejected(self):
        changes = ({"cold_start_limit": -1}, {"rule_learning_limit": True}, {"max_iter": 0},
                   {"exploration_rate": -0.1}, {"exploration_rate": 1.1}, {"C": 0},
                   {"tol": float("nan")}, {"C": float("inf")}, {"tol": True},
                   {"solver": "liblinear"}, {"l1_ratio": 1}, {"warm_start": True},
                   {"class_weight": "balanced"})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(LearnedSettings(), **change)

    def test_settings_json_rejects_unknown_and_missing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            for data in ([], {}, {"extra": 1}):
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    LearnedSettings.load(path)


class LearnedDemoTests(unittest.TestCase):
    def run_demo(self, *args, check=True):
        return subprocess.run([sys.executable, "-m", "recommendation.demo", "--method", "learned", *args],
                              cwd=ROOT, capture_output=True, text=True, check=check)

    def test_no_history_demo_is_cold_start(self):
        output = self.run_demo().stdout
        self.assertIn("Öğrenen modu: soguk_baslangic", output)
        self.assertIn("Rastgele seçim nedeni: yetersiz_karar", output)
        self.assertIn("Geçerli karar: 0", output)
        self.assertNotIn("Model olasılığı", output)

    def test_sample_history_demo_trains_real_model(self):
        data = build_training_data(load_history(ROOT / "tests" / "sample_history.json"), user_id="demo")
        self.assertEqual((data.decision_count, data.rule_decision_count), (12, 6))
        self.assertEqual((data.positive_count, data.negative_count), (12, 12))
        output = self.run_demo("--history", "tests/sample_history.json").stdout
        self.assertIn("Öğrenen modu: model", output)
        self.assertIn("Geçerli karar: 12 | Kural kararı: 6", output)
        self.assertIn("Model olasılığı P(y=1):", output)

    def test_seed_31_demo_explores(self):
        output = self.run_demo("--history", "tests/sample_history.json", "--seed", "31").stdout
        self.assertIn("Öğrenen modu: kesif", output)
        self.assertNotIn("Model olasılığı", output)

    def test_empty_pool_demo(self):
        output = self.run_demo("--temperature", "50", "--weather", "gunesli").stdout
        self.assertIn("Öğrenen Kart üretilemedi: uygun aday yok.", output)

    def test_other_user_history_is_rejected(self):
        result = self.run_demo("--history", "tests/sample_history.json", "--user-id", "other", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("başka kullanıcı", result.stderr)


if __name__ == "__main__":
    unittest.main()

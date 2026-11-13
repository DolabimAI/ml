import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from recommendation.features import encode_outfit, feature_names
from recommendation.filter import Outfit
from recommendation.history import ComparisonDecision, build_training_data, load_history, main_outfit_key
from recommendation.models import Weather, load_wardrobe


ROOT = Path(__file__).resolve().parents[1]
ITEMS = {i.id: i for i in load_wardrobe(ROOT / "tests" / "sample_wardrobe.json")}
RULE = Outfit("ust_alt", tuple(ITEMS[i] for i in (1, 9, 17)))
LEARNED = Outfit("ust_alt", tuple(ITEMS[i] for i in (2, 9, 17)))
FINAL = Outfit("ust_alt", tuple(ITEMS[i] for i in (7, 9, 17)))
WEATHER = Weather(24, "yagmurlu")
START = datetime(2000, 1, 1, tzinfo=timezone.utc)


def decision(key: str = "KT", index: int = 0, **changes: Any) -> ComparisonDecision:
    base = ComparisonDecision(
        user_id="demo", comparison_id=f"c{index:03}", result_key=key,
        completed_at=START + timedelta(minutes=index), weather=WEATHER, style="gunluk",
        rule_outfit=RULE, learned_outfit=LEARNED,
        final_outfit=FINAL if key in ("KD", "OD") else None,
    )
    # Hata testleri bilerek geçersiz alan değerleri de gönderebilir.
    return replace(base, **changes)


def rows(data):
    return [(e.source_method, main_outfit_key(e.outfit), e.label) for e in data.examples]


class HistoryExamplesTests(unittest.TestCase):
    def test_all_seven_learning_results_match_document_table(self):
        r, l, f = RULE.key, LEARNED.key, FINAL.key
        expected = {
            "KT": [("kural", r, 1), ("ogrenen", l, 0)],
            "OT": [("ogrenen", l, 1), ("kural", r, 0)],
            "KD": [("kural", f, 1), ("kural", r, 0), ("ogrenen", l, 0)],
            "OD": [("ogrenen", f, 1), ("ogrenen", l, 0), ("kural", r, 0)],
            "KR": [("kural", r, 0), ("ogrenen", l, 0), ("kural", f, 0)],
            "OR": [("kural", r, 0), ("ogrenen", l, 0), ("ogrenen", f, 0)],
            "HB": [("kural", r, 0), ("ogrenen", l, 0)],
        }
        for key, expected_rows in expected.items():
            with self.subTest(key=key):
                record = decision(key) if key in ("KT", "OT") else decision(key, final_outfit=FINAL)
                data = build_training_data([record], user_id="demo")
                self.assertEqual(rows(data), expected_rows)
                self.assertEqual(data.decision_count, 1)
                self.assertEqual(data.rule_decision_count, int(key.startswith("K")))

    def test_seven_ignored_results_produce_no_examples_or_counts(self):
        for key in ("BK", "KS", "OS", "AT", "AD", "AR", "TP"):
            with self.subTest(key=key):
                data = build_training_data([decision(key, rule_outfit=None, learned_outfit=None)], user_id="demo")
                self.assertEqual((data.examples, data.decision_count, data.rule_decision_count), ((), 0, 0))

    def test_rejection_without_change_has_only_two_examples(self):
        for key, original in (("KR", RULE), ("OR", LEARNED)):
            for final in (None, original, replace(original, items=original.items + (ITEMS[34],))):
                data = build_training_data([decision(key, final_outfit=final)], user_id="demo")
                self.assertEqual(len(data.examples), 2)
                self.assertEqual(data.positive_count, 0)

    def test_same_outfit_label_is_deduplicated_within_one_comparison(self):
        data = build_training_data([decision("KR", final_outfit=LEARNED)], user_id="demo")
        self.assertEqual(len(data.examples), 2)
        data = build_training_data([decision("HB", learned_outfit=replace(RULE, items=RULE.items + (ITEMS[34],)))], user_id="demo")
        self.assertEqual(len(data.examples), 1)

    def test_different_labels_are_preserved_when_final_returns_to_original(self):
        data = build_training_data([decision("KD", final_outfit=RULE)], user_id="demo")
        self.assertEqual([(e.outfit.key, e.label) for e in data.examples],
                         [(RULE.key, 1), (RULE.key, 0), (LEARNED.key, 0)])

    def test_different_comparisons_keep_repeated_examples(self):
        data = build_training_data([decision(index=i) for i in range(3)], user_id="demo")
        self.assertEqual((len(data.examples), data.decision_count), (6, 3))

    def test_features_use_historical_snapshot_and_context(self):
        old = replace(RULE, items=tuple(replace(i, status="silindi") for i in RULE.items))
        context = Weather(-5, "karli")
        data = build_training_data([decision(rule_outfit=old, weather=context, style="davet")], user_id="demo")
        self.assertEqual(data.examples[0].features, encode_outfit(old, context, "davet"))
        named = dict(zip(feature_names(), data.examples[0].features))
        self.assertEqual(named["context.feels_like_temp"], -5)
        self.assertEqual(named["context.style=davet"], 1)

    def test_accessories_do_not_change_training_features(self):
        first = build_training_data([decision()], user_id="demo")
        second = build_training_data([decision(rule_outfit=replace(RULE, items=RULE.items + (ITEMS[34],)))], user_id="demo")
        self.assertEqual([e.features for e in first.examples], [e.features for e in second.examples])


class HistoryCounterTests(unittest.TestCase):
    def test_ninth_tenth_and_eleventh_rule_decisions(self):
        for count, expected_rule_examples in ((0, 0), (9, 9), (10, 10), (11, 10)):
            with self.subTest(count=count):
                data = build_training_data([decision(index=i) for i in range(count)], user_id="demo")
                self.assertEqual((data.decision_count, data.rule_decision_count), (count, count))
                self.assertEqual(data.positive_count, expected_rule_examples)
                self.assertEqual(data.negative_count, count)

    def test_every_result_excludes_new_rule_examples_after_limit(self):
        prefix = [decision(index=i) for i in range(10)]
        expected = {"KT": 1, "KD": 1, "KR": 1, "OT": 1, "OD": 2, "OR": 2, "HB": 1}
        for key, count in expected.items():
            with self.subTest(key=key):
                last = decision(key, 10, final_outfit=FINAL if key not in ("KT", "OT") else None)
                data = build_training_data(prefix + [last], user_id="demo")
                recent = [e for e in data.examples if e.comparison_id == last.comparison_id]
                self.assertEqual(len(recent), count)
                self.assertTrue(all(e.source_method == "ogrenen" for e in recent))
                self.assertEqual(data.examples[:20], build_training_data(prefix, user_id="demo").examples)

    def test_general_counter_is_independent_from_rule_counter(self):
        history = [decision("OT", i) for i in range(12)] + [decision("HB", 12), decision("KD", 13)]
        data = build_training_data(history, user_id="demo")
        self.assertEqual((data.decision_count, data.rule_decision_count), (14, 1))
        self.assertEqual(len(data.examples), 29)

    def test_sorting_uses_completion_time_then_id(self):
        # Aynı anda biten kayıtlarda kimlik sırası, son kota hakkını belirler.
        first = decision("KT", 0)
        second = decision("OT", 1, completed_at=START.astimezone(timezone(timedelta(hours=3))))
        expected = build_training_data([first, second], user_id="demo", rule_learning_limit=1)
        actual = build_training_data([second, first], user_id="demo", rule_learning_limit=1)
        self.assertEqual(actual, expected)
        self.assertEqual([e.source_method for e in actual.examples], ["kural", "ogrenen", "ogrenen"])

    def test_hicbiri_before_and_after_rule_limit(self):
        history = [decision("HB", 0), decision("KT", 1), decision("HB", 2)]
        data = build_training_data(history, user_id="demo", rule_learning_limit=1)
        self.assertEqual([e.source_method for e in data.examples],
                         ["kural", "ogrenen", "kural", "ogrenen", "ogrenen"])

    def test_zero_rule_limit_excludes_rule_examples_immediately(self):
        data = build_training_data([decision("OT")], user_id="demo", rule_learning_limit=0)
        self.assertEqual(rows(data), [("ogrenen", LEARNED.key, 1)])


class HistoryValidationTests(unittest.TestCase):
    def test_other_user_and_duplicate_comparison_ids_are_rejected(self):
        for history in ([decision(user_id="other")], [decision(), decision()],
                        [decision("BK", user_id="other")]):
            with self.assertRaises(ValueError):
                build_training_data(history, user_id="demo")

    def test_unknown_result_and_invalid_identifiers_are_rejected(self):
        for changes in ({"result_key": "KURAL_TEMIZ"}, {"result_key": "??"},
                        {"user_id": ""}, {"comparison_id": ""}, {"style": "yanlis"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(decision(), **changes)

    def test_completed_decisions_require_timezone_aware_time(self):
        for value in (None, datetime(2000, 1, 1), "2000-01-01"):
            with self.assertRaises(ValueError):
                decision(completed_at=value)
        self.assertIsNone(decision("BK", completed_at=None).completed_at)

    def test_missing_outfits_and_changed_clean_final_are_rejected(self):
        for key, changes in (("KT", {"rule_outfit": None}), ("HB", {"learned_outfit": None}),
                             ("KD", {"final_outfit": None}), ("OD", {"final_outfit": None}),
                             ("KT", {"final_outfit": FINAL})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                replace(decision(key), **changes)

    def test_invalid_limit_and_empty_user_are_rejected(self):
        # Çalışma anındaki tür denetimini sınamak için yanlış türler kasıtlıdır.
        invalid_limits: tuple[Any, ...] = (-1, True, 1.5)
        for value in invalid_limits:
            with self.assertRaises(ValueError):
                build_training_data([], user_id="demo", rule_learning_limit=value)
        with self.assertRaises(ValueError):
            build_training_data([], user_id="")

    def test_json_round_trip_contains_snapshots(self):
        record = decision("KD")
        raw = asdict(record)
        assert record.completed_at is not None
        raw["completed_at"] = record.completed_at.isoformat()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_text(json.dumps([raw]), encoding="utf-8")
            self.assertEqual(load_history(path), (record,))

    def test_bad_json_shapes_and_dates_are_rejected(self):
        raw = json.loads(json.dumps(asdict(decision()), default=lambda value: value.isoformat()))
        invalid = [{}, [], {**raw, "extra": 1}, {**raw, "completed_at": 5},
                   {**raw, "completed_at": "bad"}, {**raw, "weather": {}},
                   {**raw, "rule_outfit": {"template": "ust_alt", "items": [5]}}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ComparisonDecision.from_dict(value)


if __name__ == "__main__":
    unittest.main()

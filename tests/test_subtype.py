import json
import unittest

import numpy as np

from service import codes
from vision.subtype import SubtypePredictor, load_subtype_settings, softmax_scores

S = load_subtype_settings()
VALUES = list(S["labels"])


class FakeEmbedder:
    """35 ifade için birim vektörler; görüntü gömmesi istenen alt türe doğru çekilir."""

    logit_scale = 100.0

    def __init__(self, target: str, strength: float):
        self.target, self.strength = target, strength

    def encode_texts(self, texts):
        return np.eye(len(texts))

    def encode_image(self, image):
        v = np.ones(len(VALUES))
        v[VALUES.index(self.target)] += self.strength
        return v


class LabelTest(unittest.TestCase):
    def test_35_labels_match_shared_codes_in_order(self):
        self.assertEqual(VALUES, list(codes.subtype_values()))

    def test_every_label_is_an_english_photo_prompt(self):
        for v, text in S["labels"].items():
            self.assertTrue(text.startswith("a photo of "), v)
        self.assertEqual(len(set(S["labels"].values())), 35)

    def test_plan_example_phrases(self):
        self.assertEqual(S["labels"]["tisort"], "a photo of a t-shirt")
        self.assertEqual(S["labels"]["klasik_ayakkabi"], "a photo of leather dress shoes")

    def test_threshold_is_040(self):
        self.assertEqual(S["confidence_threshold"], 0.40)

    def test_label_keys_mismatch_is_rejected(self):
        bad = json.loads(json.dumps(S))
        bad["labels"].pop("tisort")
        import tempfile, pathlib

        p = pathlib.Path(tempfile.mkdtemp()) / "s.json"
        p.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_subtype_settings(p)


class ScoringTest(unittest.TestCase):
    def test_softmax_sums_to_one(self):
        rng = np.random.default_rng(0)
        p = softmax_scores(rng.normal(size=16), rng.normal(size=(35, 16)), 100.0)
        self.assertAlmostEqual(float(p.sum()), 1.0)
        self.assertTrue((p >= 0).all())

    def test_confident_prediction_returns_subtype(self):
        r = SubtypePredictor(FakeEmbedder("gomlek", 5.0), S).predict(object())
        self.assertEqual((r.subtype, r.top_subtype), ("gomlek", "gomlek"))
        self.assertGreaterEqual(r.confidence, 0.40)

    def test_low_confidence_returns_empty_subtype_but_keeps_top(self):
        """Plan: güven 0,40'ın altındaysa alt tür boş, en yüksek tahmin ve güven yine döner."""
        r = SubtypePredictor(FakeEmbedder("kazak", 0.0), S).predict(object())
        self.assertIsNone(r.subtype)
        self.assertIn(r.top_subtype, VALUES)
        self.assertLess(r.confidence, 0.40)
        self.assertGreater(r.confidence, 0.0)

    def test_returned_codes_are_in_shared_list(self):
        for target in ("bot", "elbise", "gunes_gozlugu"):
            r = SubtypePredictor(FakeEmbedder(target, 5.0), S).predict(object())
            self.assertIn(r.top_subtype, codes.subtype_values())


if __name__ == "__main__":
    unittest.main()

import random
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

from recommendation.filter import generate_candidates
from recommendation.models import ClothingItem, FilterSettings, Weather, load_catalog, load_wardrobe


def item(subtype, item_id, **changes):
    source = next(s for s in load_catalog()["subtypes"] if s["value"] == subtype)
    result = ClothingItem(
        id=item_id, subtype=subtype, category=source["category"], color="gri", tone="orta",
        is_patterned=False, styles=tuple(source["styles"]), min_temp=source["min_temp"],
        max_temp=source["max_temp"], avoid_when_wet=source["avoid_when_wet"],
        preferred_when_wet=source["preferred_when_wet"],
        preferred_when_hot=source["preferred_when_hot"], status="onayli",
    )
    return replace(result, **changes)


class FilterTests(unittest.TestCase):
    def pool(self, clothes, temp=24, weather="kapali", style="gunluk", **kwargs):
        return generate_candidates(clothes, Weather(temp, weather), style,
                                   rng=random.Random(42), **kwargs)

    def summer(self, shoe="spor_ayakkabi"):
        return [item("tisort", 1), item("sort", 2), item(shoe, 3)]

    def business(self):
        return [item("gomlek", 1), item("kumas_pantolon", 2),
                item("klasik_ayakkabi", 3), item("babet", 4)]

    def test_sample_wardrobe_meets_both_template_minimums(self):
        wardrobe = load_wardrobe(Path(__file__).parent / "sample_wardrobe.json")
        counts = Counter(i.category for i in wardrobe if i.status == "onayli")
        for category, minimum in {"ust": 6, "alt": 5, "ayakkabi": 3, "dis": 2, "tek_parca": 5}.items():
            self.assertGreaterEqual(counts[category], minimum)
        self.assertEqual(len(wardrobe), len({i.id for i in wardrobe}))

    def test_both_templates_and_accessory_exclusion(self):
        clothes = [item("tisort", 1), item("kot", 2), item("spor_ayakkabi", 3),
                   item("elbise", 4), item("atki", 5)]
        result = self.pool(clothes, temp=20)
        self.assertEqual({c.key for c in result.candidates}, {(1, 2, 3), (3, 4)})
        self.assertEqual({c.template for c in result.candidates}, {"ust_alt", "tek_parca"})

    def test_one_piece_does_not_require_top_or_bottom(self):
        result = self.pool([item("elbise", 1), item("spor_ayakkabi", 2)])
        self.assertEqual([c.key for c in result.candidates], [(1, 2)])

    def test_temperature_boundaries_are_inclusive(self):
        clothes = [item("kazak", 1), item("kot", 2), item("bot", 3)]
        for temp in (-20, 15):
            with self.subTest(temp=temp):
                self.assertEqual(len(self.pool(clothes, temp=temp).candidates), 1)
        for temp in (-20.1, 15.1):
            with self.subTest(temp=temp):
                self.assertFalse(self.pool(clothes, temp=temp).candidates)

    def test_current_item_style_overrides_subtype_default(self):
        clothes = [item("gomlek", 1, styles=("gunluk",)),
                   item("kot", 2), item("spor_ayakkabi", 3)]
        self.assertEqual(len(self.pool(clothes).candidates), 1)
        self.assertFalse(self.pool(clothes, style="is").candidates)

    def test_only_approved_items_are_candidates(self):
        clothes = self.summer() + [item("tisort", 4, status="taslak"),
                                   item("tisort", 5, status="silindi")]
        self.assertEqual([c.key for c in self.pool(clothes).candidates], [(1, 2, 3)])

    def test_all_wet_conditions_exclude_avoided_shoes_when_alternative_exists(self):
        clothes = self.summer() + [item("sandalet", 4), item("terlik", 5), item("babet", 6)]
        for condition in ("yagmurlu", "karli", "firtinali"):
            with self.subTest(condition=condition):
                result = self.pool(clothes, weather=condition)
                self.assertEqual([c.key for c in result.candidates], [(1, 2, 3)])
                self.assertFalse(result.fallback_slots)

    def test_wet_fallback_keeps_only_previously_eligible_shoes(self):
        clothes = self.summer("sandalet") + [item("bot", 4), item("klasik_ayakkabi", 5)]
        result = self.pool(clothes, weather="yagmurlu")
        self.assertEqual([c.key for c in result.candidates], [(1, 2, 3)])
        self.assertEqual(result.fallback_slots, ("islak:ayakkabi",))

    def test_no_weather_fallback_for_temperature_or_style_failure(self):
        for shoe in ("bot", "klasik_ayakkabi"):
            with self.subTest(shoe=shoe):
                result = self.pool(self.summer(shoe), weather="yagmurlu")
                self.assertFalse(result.candidates)
                self.assertNotIn("islak:ayakkabi", result.fallback_slots)

    def test_outerwear_added_when_eligible_even_when_dry(self):
        clothes = [item("kazak", 1), item("kot", 2), item("bot", 3), item("mont", 4)]
        result = self.pool(clothes, temp=6)
        self.assertEqual([c.key for c in result.candidates], [(1, 2, 3, 4)])

    def test_wet_outerwear_preference(self):
        clothes = [item("kazak", 1), item("kot", 2), item("bot", 3),
                   item("mont", 4), item("yagmurluk", 5), item("ceket", 6)]
        result = self.pool(clothes, temp=10, weather="yagmurlu")
        self.assertEqual({c.key for c in result.candidates}, {(1, 2, 3, 4), (1, 2, 3, 5)})

    def test_wet_outerwear_fallback_preserves_eligible_nonpreferred_piece(self):
        clothes = [item("kazak", 1), item("kot", 2), item("bot", 3), item("kaban", 4)]
        result = self.pool(clothes, temp=6, weather="yagmurlu")
        self.assertEqual([c.key for c in result.candidates], [(1, 2, 3, 4)])
        self.assertEqual(result.fallback_slots, ("islak:dis",))

    def test_rain_does_not_restore_temperature_ineligible_outerwear(self):
        clothes = [item("kazak", 1), item("kot", 2), item("bot", 3), item("yagmurluk", 4)]
        result = self.pool(clothes, temp=0, weather="yagmurlu")
        self.assertEqual([c.key for c in result.candidates], [(1, 2, 3)])

    def test_hot_rule_requires_sun_and_inclusive_threshold(self):
        for temp, condition, shoes in ((24.9, "gunesli", {3, 4}),
                                       (25, "gunesli", {4}),
                                       (28, "kapali", {3, 4})):
            with self.subTest(temp=temp, condition=condition):
                result = self.pool(self.business(), temp=temp, weather=condition, style="is")
                actual = {i.id for c in result.candidates for i in c.items if i.category == "ayakkabi"}
                self.assertEqual(actual, shoes)

    def test_hot_preference_does_not_exclude_tops(self):
        result = self.pool(self.summer(), temp=28, weather="gunesli")
        self.assertEqual([c.key for c in result.candidates], [(1, 2, 3)])

    def test_hot_fallback_preserves_eligible_shoe(self):
        result = self.pool(self.business()[:3], temp=28, weather="gunesli", style="is")
        self.assertEqual([c.key for c in result.candidates], [(1, 2, 3)])
        self.assertEqual(result.fallback_slots, ("sicak:ayakkabi",))

    def test_wet_day_does_not_apply_hot_preference(self):
        result = self.pool(self.business(), temp=28, weather="yagmurlu", style="is")
        self.assertEqual([c.key for c in result.candidates], [(1, 2, 3)])
        self.assertFalse(result.fallback_slots)

    def test_rejected_key_ignores_order_and_includes_outerwear(self):
        clothes = [item("kazak", 1), item("kot", 2), item("bot", 3),
                   item("mont", 4), item("mont", 5)]
        result = self.pool(clothes, temp=6, rejected_outfits=[(4, 2, 1, 3)])
        self.assertEqual([c.key for c in result.candidates], [(1, 2, 3, 5)])

    def test_fallback_never_relaxes_rejection(self):
        result = self.pool(self.summer("sandalet"), weather="yagmurlu", rejected_outfits=[(3, 1, 2)])
        self.assertFalse(result.candidates)
        self.assertEqual(result.fallback_slots, ("islak:ayakkabi",))

    def test_rejections_are_not_remembered_across_calls(self):
        self.assertFalse(self.pool(self.summer(), rejected_outfits=[(1, 2, 3)]).candidates)
        self.assertEqual(len(self.pool(self.summer()).candidates), 1)

    def test_empty_wardrobe_and_missing_shoes(self):
        self.assertFalse(self.pool([]).candidates)
        self.assertFalse(self.pool([item("tisort", 1), item("sort", 2)]).candidates)

    def test_all_valid_combinations_are_returned_without_duplicates(self):
        clothes = self.summer() + [item("tisort", 4), item("sort", 5),
                                   item("spor_ayakkabi", 6), item("elbise", 7)]
        expected = {tuple(sorted((top, bottom, shoe)))
                    for top in (1, 4) for bottom in (2, 5) for shoe in (3, 6)}
        expected |= {(3, 7), (6, 7)}
        result = self.pool(clothes)
        self.assertEqual(len(result.candidates), len(expected))
        self.assertEqual({c.key for c in result.candidates}, expected)

    def test_candidate_limit_does_not_materialize_billion_combinations(self):
        clothes = [item(subtype, group * 1000 + n + 1)
                   for group, subtype in enumerate(("tisort", "sort", "spor_ayakkabi"))
                   for n in range(1000)]
        result = self.pool(clothes, settings=FilterSettings(25, 7))
        self.assertEqual(result.candidate_space_size, 1_000_000_000)
        self.assertEqual(len(result.candidates), 7)
        self.assertEqual(len({c.key for c in result.candidates}), 7)
        self.assertTrue(result.limit_reached)

    def test_limit_is_applied_after_rejections(self):
        clothes = self.summer() + [item("tisort", n) for n in range(4, 15)]
        all_keys = [c.key for c in self.pool(clothes).candidates]
        result = self.pool(clothes, rejected_outfits=all_keys[:-1], settings=FilterSettings(25, 1))
        self.assertEqual([c.key for c in result.candidates], all_keys[-1:])

    def test_fixed_seed_is_reproducible(self):
        clothes = self.summer() + [item("tisort", n) for n in range(4, 15)]
        self.assertEqual(self.pool(clothes, settings=FilterSettings(25, 3)),
                         self.pool(clothes, settings=FilterSettings(25, 3)))

    def test_hot_threshold_is_configurable(self):
        result = self.pool(self.business(), temp=25, weather="gunesli", style="is",
                           settings=FilterSettings(30, 10))
        self.assertEqual(len(result.candidates), 2)

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            self.pool(self.summer() + [item("tisort", 1)])

    def test_invalid_context_is_rejected(self):
        with self.assertRaises(ValueError):
            self.pool(self.summer(), style="bilinmeyen")
        with self.assertRaises(ValueError):
            Weather(24, "rain")
        for temp in (float("nan"), float("inf"), True):
            with self.subTest(temp=temp), self.assertRaises(ValueError):
                Weather(temp, "gunesli")

    def test_notebook_example_unknown_codes_are_rejected(self):
        for change in ({"color": "bordo"}, {"subtype": "trenckot"}, {"category": "dis_giyim"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(item("mont", 1), **change)

    def test_invalid_values_and_missing_flags_are_rejected(self):
        for changes in ({"min_temp": 50, "max_temp": 20}, {"avoid_when_wet": "false"},
                        {"avoid_when_wet": True, "preferred_when_wet": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                item("mont", 1, **changes)
        with self.assertRaises(ValueError):
            ClothingItem.from_dict({"id": 1})
        for limit in (0, -1, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                FilterSettings(25, limit)


if __name__ == "__main__":
    unittest.main()

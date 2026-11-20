import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from recommendation.accessory import (
    AccessorySettings,
    accessory_candidates,
    rank_accessories,
    select_accessories,
)
from recommendation.filter import Outfit, generate_candidates
from recommendation.models import Weather, load_catalog, load_wardrobe
from recommendation.rule_based import select_rule_outfit


ROOT = Path(__file__).resolve().parents[1]
WARDROBE = load_wardrobe(ROOT / "tests" / "sample_wardrobe.json")
SETTINGS_PATH = ROOT / "recommendation" / "accessory_settings.json"
ALL_ACCESSORIES = ("atki", "bere", "eldiven", "sapka", "gunes_gozlugu")


def item(subtype, color, item_id, **changes):
    """Örnek dolaptaki aynı kategoriden bir parçayı yeni alt tür, renk ve id ile kopyalar."""
    row = next(s for s in load_catalog()["subtypes"] if s["value"] == subtype)
    base = next(i for i in WARDROBE if i.category == row["category"])
    values = dict(id=item_id, subtype=subtype, category=row["category"], color=color,
                  styles=tuple(row["styles"]), min_temp=row["min_temp"], max_temp=row["max_temp"],
                  avoid_when_wet=row["avoid_when_wet"], preferred_when_wet=row["preferred_when_wet"],
                  preferred_when_hot=row["preferred_when_hot"], status="onayli")
    values.update(changes)
    return replace(base, **values)


def accessories(*subtypes, start_id=100, color="siyah"):
    return tuple(item(subtype, color, start_id + index) for index, subtype in enumerate(subtypes))


def card(reference_color, *, with_dis=False, single_piece=False, id_offset=0):
    """Referans parçası belli renkte olan bir kombin; diğer parçalar nötrdür."""
    if single_piece:
        items = (item("elbise", reference_color, id_offset + 1),
                 item("spor_ayakkabi", "siyah", id_offset + 2))
        template = "tek_parca"
    else:
        top_color = "beyaz" if with_dis else reference_color
        items = (item("tisort", top_color, id_offset + 1), item("kot", "lacivert", id_offset + 2),
                 item("spor_ayakkabi", "siyah", id_offset + 3))
        template = "ust_alt"
    if with_dis:
        items += (item("mont", reference_color, id_offset + 9),)
    return Outfit(template, items)


COLD = Weather(5, "parcali_bulutlu")
HOT_SUNNY = Weather(28, "gunesli")  # Elle verilen hava: 28 °C, güneşli, öğle.
NEUTRAL_CARD = card("siyah")


def chosen_subtypes(choices):
    return tuple(choice.item.subtype for choice in choices)


def select(wardrobe, weather, style="gunluk", *, cards=(NEUTRAL_CARD,), is_daytime=True,
           wants_accessories=True, seed=42):
    return select_accessories(cards, wardrobe, weather, style, is_daytime=is_daytime,
                              wants_accessories=wants_accessories, rng=random.Random(seed))


class AccessorySettingsTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accessory_settings.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return AccessorySettings.load(path)

    def test_thresholds_and_groups_match_plan(self):
        settings = AccessorySettings.load()
        self.assertEqual(settings.cold_below_c, 10)
        self.assertEqual(settings.cold_subtypes, ("atki", "bere", "eldiven"))
        self.assertEqual(settings.warm_above_c, 20)
        self.assertEqual(settings.warm_subtypes, ("sapka", "gunes_gozlugu"))

    def test_permission_table_matches_project_plan(self):
        # Proje Planı, aksesuar izin tablosu.
        expected = {
            "gunluk": {"atki", "bere", "eldiven", "sapka", "gunes_gozlugu"},
            "is": {"atki", "eldiven", "gunes_gozlugu"},
            "spor": {"bere", "sapka", "gunes_gozlugu"},
            "davet": {"atki", "eldiven"},
        }
        settings = AccessorySettings.load()
        self.assertEqual({style: set(allowed) for style, allowed in settings.allowed_by_style.items()},
                         expected)

    def test_permission_table_matches_accessory_styles_in_catalog_and_shared_table(self):
        # Ortak kod listesi: aksesuar satırlarındaki tarzlar izin tablosundan yazılır.
        settings = AccessorySettings.load()
        shared = json.loads((ROOT / "shared" / "subtypes.json").read_text(encoding="utf-8"))
        for rows in (load_catalog()["subtypes"], shared["subtypes"]):
            for row in rows:
                if row["category"] != "aksesuar":
                    continue
                with self.subTest(subtype=row["value"]):
                    allowed_styles = {style for style, allowed in settings.allowed_by_style.items()
                                      if row["value"] in allowed}
                    self.assertEqual(allowed_styles, set(row["styles"]))

    def test_rejects_invalid_settings(self):
        cases = {
            "unknown_field": {**self.data, "extra": 1},
            "missing_field": {k: v for k, v in self.data.items() if k != "warm_above_c"},
            "unknown_subtype": {**self.data, "cold_subtypes": ["atki", "kazak"]},
            "non_accessory": {**self.data, "warm_subtypes": ["sapka", "tisort"]},
            "overlapping_groups": {**self.data, "warm_subtypes": ["sapka", "atki"]},
            "thresholds_overlap": {**self.data, "cold_below_c": 25},
            "missing_style": {**self.data, "allowed_by_style": {
                k: v for k, v in self.data["allowed_by_style"].items() if k != "davet"}},
            "unknown_style_value": {**self.data, "allowed_by_style": {
                **self.data["allowed_by_style"], "is": ["atki", "kravat"]}},
            "bool_threshold": {**self.data, "cold_below_c": True},
        }
        for name, data in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.load(data)


class AccessoryRuleTests(unittest.TestCase):
    """T-27: aksesuar kuralının aday adımları."""

    def setUp(self):
        self.wardrobe = accessories(*ALL_ACCESSORIES)

    def test_t27_no_accessories_when_not_wanted(self):
        for weather in (COLD, HOT_SUNNY):
            with self.subTest(weather=weather):
                self.assertEqual(select(self.wardrobe, weather, wants_accessories=False), ())

    def test_t27_cold_below_10_gives_scarf_beanie_gloves(self):
        self.assertEqual(chosen_subtypes(select(self.wardrobe, COLD)), ("atki", "bere", "eldiven"))

    def test_cold_threshold_is_strict(self):
        self.assertEqual(select(self.wardrobe, Weather(10, "kapali")), ())
        self.assertEqual(chosen_subtypes(select(self.wardrobe, Weather(9.9, "kapali"))),
                         ("atki", "bere", "eldiven"))

    def test_cold_rule_uses_feels_like_temperature_regardless_of_sky(self):
        for condition in ("gunesli", "yagmurlu", "karli", "firtinali"):
            with self.subTest(condition=condition):
                result = select(self.wardrobe, Weather(-3, condition), is_daytime=False)
                self.assertEqual(chosen_subtypes(result), ("atki", "bere", "eldiven"))

    def test_t27_hat_and_sunglasses_on_given_28c_sunny_noon(self):
        self.assertEqual(chosen_subtypes(select(self.wardrobe, HOT_SUNNY, is_daytime=True)),
                         ("sapka", "gunes_gozlugu"))

    def test_warm_threshold_is_strict(self):
        self.assertEqual(select(self.wardrobe, Weather(20, "gunesli")), ())
        self.assertEqual(chosen_subtypes(select(self.wardrobe, Weather(20.5, "gunesli"))),
                         ("sapka", "gunes_gozlugu"))

    def test_t27_no_hat_or_sunglasses_in_evening_or_night(self):
        self.assertEqual(select(self.wardrobe, HOT_SUNNY, is_daytime=False), ())

    def test_hat_and_sunglasses_need_sunny_sky(self):
        for condition in ("parcali_bulutlu", "kapali", "sisli", "yagmurlu"):
            with self.subTest(condition=condition):
                self.assertEqual(select(self.wardrobe, Weather(28, condition)), ())

    def test_mild_weather_gives_no_accessory(self):
        self.assertEqual(select(self.wardrobe, Weather(15, "gunesli")), ())

    def test_t27_no_beanie_at_invitation(self):
        self.assertEqual(chosen_subtypes(select(self.wardrobe, COLD, "davet")), ("atki", "eldiven"))

    def test_permission_table_is_applied_for_every_style(self):
        expected = {
            ("gunluk", "cold"): ("atki", "bere", "eldiven"),
            ("is", "cold"): ("atki", "eldiven"),
            ("spor", "cold"): ("bere",),
            ("davet", "cold"): ("atki", "eldiven"),
            ("gunluk", "hot"): ("sapka", "gunes_gozlugu"),
            ("is", "hot"): ("gunes_gozlugu",),
            ("spor", "hot"): ("sapka", "gunes_gozlugu"),
            ("davet", "hot"): (),
        }
        for (style, kind), subtypes in expected.items():
            weather = COLD if kind == "cold" else HOT_SUNNY
            with self.subTest(style=style, kind=kind):
                self.assertEqual(chosen_subtypes(select(self.wardrobe, weather, style)), subtypes)

    def test_accessory_not_in_wardrobe_is_dropped(self):
        wardrobe = accessories("atki", "sapka")
        self.assertEqual(chosen_subtypes(select(wardrobe, COLD)), ("atki",))
        self.assertEqual(chosen_subtypes(select(wardrobe, HOT_SUNNY)), ("sapka",))
        self.assertEqual(select(accessories(), COLD), ())

    def test_only_approved_accessories_are_used(self):
        wardrobe = (item("atki", "gri", 1, status="taslak"), item("bere", "gri", 2, status="silindi"),
                    item("eldiven", "gri", 3))
        self.assertEqual(chosen_subtypes(select(wardrobe, COLD)), ("eldiven",))

    def test_item_style_field_does_not_override_permission_table(self):
        # Aksesuar tarzı yalnız ekranda görünür; izin tablosu Python ayarıdır.
        wardrobe = (item("bere", "gri", 1, styles=("davet",)),)
        self.assertEqual(select(wardrobe, COLD, "davet"), ())

    def test_main_garments_are_ignored(self):
        self.assertEqual(select(WARDROBE[:10], COLD), ())

    def test_candidates_are_grouped_by_subtype(self):
        wardrobe = accessories("atki", "atki", "bere") + (item("eldiven", "gri", 1, status="taslak"),)
        candidates = accessory_candidates(wardrobe, COLD, "gunluk", is_daytime=True,
                                          wants_accessories=True)
        self.assertEqual(list(candidates), ["atki", "bere"])
        self.assertEqual([i.id for i in candidates["atki"]], [100, 101])

    def test_unknown_style_and_duplicate_ids_raise(self):
        with self.assertRaises(ValueError):
            select(self.wardrobe, COLD, "parti")
        with self.assertRaises(ValueError):
            select(self.wardrobe + (item("atki", "gri", 100),), COLD)

    def test_daytime_and_wish_flags_must_be_bool(self):
        with self.assertRaises(ValueError):
            select(self.wardrobe, COLD, is_daytime=1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            select(self.wardrobe, COLD, wants_accessories="evet")  # type: ignore[arg-type]


class AccessorySelectionTests(unittest.TestCase):
    """T-28'in seçim kısmı: aynı türden birden fazla aday."""

    def setUp(self):
        # Sol kart kırmızı, sağ kart mavi. Pembe atkı: (3 + 1) / 2 = 2,0;
        # yeşil atkı: (2 + 3) / 2 = 2,5. Yalnız sol karta bakılsa pembe seçilirdi.
        self.pink = item("atki", "pembe", 201)
        self.green = item("atki", "yesil", 202)
        self.wardrobe = (self.pink, self.green)
        self.left = card("kirmizi", id_offset=0)
        self.right = card("mavi", id_offset=10)

    def test_t28_choice_uses_average_of_both_cards(self):
        result = select(self.wardrobe, COLD, cards=(self.left, self.right))
        self.assertEqual([c.item.id for c in result], [self.green.id])
        self.assertEqual(result[0].average_score, 2.5)
        self.assertEqual(result[0].tied_best_count, 1)

    def test_single_card_uses_only_that_card(self):
        self.assertEqual(select(self.wardrobe, COLD, cards=(self.left,))[0].item, self.pink)
        self.assertEqual(select(self.wardrobe, COLD, cards=(self.right,))[0].item, self.green)

    def test_card_order_does_not_change_choice(self):
        for seed in range(10):
            with self.subTest(seed=seed):
                self.assertEqual(select(self.wardrobe, COLD, cards=(self.left, self.right), seed=seed),
                                 select(self.wardrobe, COLD, cards=(self.right, self.left), seed=seed))

    def test_t28_outerwear_is_reference_when_present(self):
        # Üst kırmızı, dış giyim mavi: karşılaştırma dış giyimle yapılır.
        with_dis = Outfit("ust_alt", (item("tisort", "kirmizi", 1), item("kot", "lacivert", 2),
                                      item("spor_ayakkabi", "siyah", 3), item("mont", "mavi", 4)))
        self.assertEqual(select(self.wardrobe, COLD, cards=(with_dis,))[0].item, self.green)

    def test_t28_top_is_reference_without_outerwear(self):
        self.assertEqual(select(self.wardrobe, COLD, cards=(card("kirmizi"),))[0].item, self.pink)

    def test_single_piece_is_reference_in_single_piece_template(self):
        self.assertEqual(select(self.wardrobe, COLD, cards=(card("kirmizi", single_piece=True),))[0].item,
                         self.pink)
        self.assertEqual(select(self.wardrobe, COLD,
                                cards=(card("kirmizi", single_piece=True, with_dis=True),))[0].item,
                         self.pink)
        self.assertEqual(select(self.wardrobe, COLD,
                                cards=(card("mavi", single_piece=True, with_dis=True),))[0].item,
                         self.green)

    def test_one_accessory_per_subtype_and_same_list_for_both_cards(self):
        wardrobe = (item("atki", "pembe", 1), item("atki", "yesil", 2), item("bere", "gri", 3),
                    item("bere", "kirmizi", 4), item("eldiven", "siyah", 5))
        result = select(wardrobe, COLD, cards=(self.left, self.right))
        self.assertEqual(chosen_subtypes(result), ("atki", "bere", "eldiven"))

    def test_ties_are_broken_randomly_with_given_seed(self):
        wardrobe = (item("atki", "gri", 1), item("atki", "siyah", 2))
        picks = {select(wardrobe, COLD, cards=(self.left, self.right), seed=seed)[0].item.id
                 for seed in range(30)}
        self.assertEqual(picks, {1, 2})
        first = select(wardrobe, COLD, cards=(self.left, self.right), seed=7)
        self.assertEqual(first, select(wardrobe, COLD, cards=(self.left, self.right), seed=7))
        self.assertEqual(first[0].tied_best_count, 2)

    def test_rank_orders_by_average_score(self):
        orange = item("atki", "turuncu", 203)
        purple = item("atki", "mor", 204)
        ranked = rank_accessories((self.pink, self.green, orange, purple), (self.left, self.right),
                                  rng=random.Random(42))
        # turuncu: (3 + 2) / 2 = 2,5; yeşil 2,5; pembe 2,0; mor: (1 + 3) / 2 = 2,0.
        self.assertEqual({r.item.id for r in ranked[:2]}, {orange.id, self.green.id})
        self.assertEqual({r.item.id for r in ranked[2:]}, {self.pink.id, purple.id})
        self.assertEqual([r.average_score for r in ranked], [2.5, 2.5, 2.0, 2.0])

    def test_rank_with_current_single_outfit(self):
        # E5 ortak_kural: seçilen kombinin o anki hâli tek kart olarak verilir.
        ranked = rank_accessories((self.pink, self.green), (self.right,), rng=random.Random(1))
        self.assertEqual([r.item for r in ranked], [self.green, self.pink])

    def test_invalid_cards_raise(self):
        for cards in ((), (self.left, self.right, card("mavi", id_offset=20))):
            with self.subTest(count=len(cards)), self.assertRaises(ValueError):
                select(self.wardrobe, COLD, cards=cards)
        no_reference = Outfit("ust_alt", (item("kot", "mavi", 1), item("spor_ayakkabi", "siyah", 2)))
        with self.assertRaises(ValueError):
            select(self.wardrobe, COLD, cards=(no_reference,))
        with self.assertRaises(ValueError):
            rank_accessories((item("tisort", "mavi", 50),), (self.left,), rng=random.Random(1))

    def test_no_card_needed_when_no_accessory_applies(self):
        # Aksesuar adayı yoksa kartlara bakılmaz; aksesuar istenmediğinde de liste boştur.
        self.assertEqual(select(self.wardrobe, Weather(15, "kapali"), cards=(self.left,)), ())


class AccessoryIntegrationTests(unittest.TestCase):
    def test_with_rule_and_learned_cards_from_one_pool(self):
        from recommendation.learned import select_learned_outfit

        for weather, is_daytime, expected in ((COLD, False, ("atki",)), (HOT_SUNNY, True, ("sapka",))):
            with self.subTest(weather=weather):
                pool = generate_candidates(WARDROBE, weather, "gunluk", rng=random.Random(42))
                self.assertTrue(pool.candidates)
                rule = select_rule_outfit(pool.candidates, rng=random.Random(42))
                learned = select_learned_outfit(pool.candidates, weather, "gunluk", (),
                                                user_id="demo", rng=random.Random(42))
                assert rule is not None and learned is not None
                cards =(rule.outfit,) if rule.outfit.key == learned.outfit.key else (
                    rule.outfit, learned.outfit)
                result = select_accessories(cards, WARDROBE, weather, "gunluk", is_daytime=is_daytime,
                                            wants_accessories=True, rng=random.Random(42))
                self.assertEqual(chosen_subtypes(result), expected)
                self.assertTrue(all(c.item.category == "aksesuar" for c in result))


if __name__ == "__main__":
    unittest.main()

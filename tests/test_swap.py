"""E5: POST /swap ucu ve değiştirme akışı.

Sözleşme örnekleri `tests/contracts/` altındadır; kaynak api deposu
`contracts/examples/` (049ce75, A3 PR #6). Sözleşme değişirse bu kopyalar da güncellenir.
"""

import copy
import json
import random
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from recommendation import router as router_module
from service.main import create_app

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "tests" / "contracts"


def contract(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _camel(name):
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def _local_history_as_contract(rows):
    """tests/sample_history.json (yerel biçim) → A3 history kayıtları."""
    def outfit(value):
        if value is None:
            return None
        return {"template": value["template"],
                "items": [{_camel(k): v for k, v in item.items()} for item in value["items"]]}

    return [{
        "comparisonId": int(row["comparison_id"].removeprefix("demo-")),
        "resultKey": row["result_key"],
        "completedAt": row["completed_at"],
        "context": {"feelsLikeTemp": row["weather"]["feels_like_temp"],
                    "weatherCondition": row["weather"]["condition"], "eventStyle": row["style"]},
        "ruleOutfit": outfit(row["rule_outfit"]),
        "learnedOutfit": outfit(row["learned_outfit"]),
        "finalOutfit": outfit(row["final_outfit"]),
    } for row in rows]


SAMPLE_HISTORY = _local_history_as_contract(
    json.loads((ROOT / "tests" / "sample_history.json").read_text(encoding="utf-8")))

# Örnek istekte (9,4 °C, yağmurlu, akşam, günlük) üst giyimden geçenler: 1, 2, 5, 6, 7.
# 1 şu anki parça, 5 dışlanmış; geriye 2, 6 ve 7 kalır.
EXAMPLE_TOP_CANDIDATES = {2, 6, 7}


def request_body(**changes):
    body = contract("swap-request.json")
    body.update(changes)
    return body


def accessory(item_id, subtype, color):
    return {"id": item_id, "subtype": subtype, "category": "aksesuar", "color": color, "tone": "orta",
            "isPatterned": False, "styles": ["gunluk", "is", "davet"], "minTemp": -30, "maxTemp": 50,
            "avoidWhenWet": False, "preferredWhenWet": False, "preferredWhenHot": False,
            "status": "onayli"}


class SwapEndpointTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.seed = 42
        self.app.dependency_overrides[router_module.get_rng] = lambda: random.Random(self.seed)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def post(self, body, seed=None):
        if seed is not None:
            self.seed = seed
        payload = body if isinstance(body, (bytes, str)) else json.dumps(body)
        return self.client.post("/swap", content=payload, headers={"Content-Type": "application/json"})

    def new_item_id(self, body, seed=None):
        response = self.post(body, seed)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        if result == {"status": "no_alternative"}:
            return None
        self.assertEqual(set(result), {"status", "newItemId"})
        self.assertEqual(result["status"], "ok")
        self.assertIs(type(result["newItemId"]), int)
        return result["newItemId"]

    def swap_until_exhausted(self, body, *, replaced_id, limit=10):
        """C8'in yapacağı gibi: her cevaptan sonra yeni parçayı koyar, eskisini dışlar."""
        body = copy.deepcopy(body)
        is_accessory = body["targetAccessoryId"] is not None
        key = "accessoryIds" if is_accessory else "itemIds"
        returned = []
        for _ in range(limit):
            new_id = self.new_item_id(body)
            if new_id is None:
                return returned
            returned.append(new_id)
            ids = body["currentOutfit"][key]
            ids[ids.index(replaced_id)] = new_id
            body["excludedItemIds"].append(replaced_id)
            if is_accessory:
                body["targetAccessoryId"] = new_id
            replaced_id = new_id
        self.fail(f"{limit} değiştirmede no_alternative gelmedi")

    def assert_invalid(self, response):
        self.assertEqual(response.status_code, 422, response.text)
        body = response.json()
        self.assertEqual(set(body), {"code", "message"})
        self.assertEqual(body["code"], "invalid_request")
        self.assertTrue(body["message"])


class ContractTests(SwapEndpointTestCase):
    def test_example_request_gets_response_in_contract_shape(self):
        response = self.post(contract("swap-request.json"))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), set(contract("swap-response.json")))
        self.assertEqual(body["status"], "ok")
        self.assertIn(body["newItemId"], EXAMPLE_TOP_CANDIDATES)

    def test_no_alternative_matches_example_exactly(self):
        body = request_body(excludedItemIds=[1, 2, 5, 6, 7])
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), contract("swap-response-no-alternative.json"))

    def test_internal_error_shape(self):
        with mock.patch.object(router_module, "swap", side_effect=RuntimeError("bozuk")), \
                self.assertLogs(router_module.log, level="ERROR"):
            response = self.post(contract("swap-request.json"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"code": "internal_error", "message": "Beklenmeyen bir hata oluştu."})


class DoneCriterionTests(SwapEndpointTestCase):
    """E5 bitti sayılır / T-26 Python kısmı: aynı kartta üç değiştirmede üç farklı parça,
    sonra no_alternative; aynı parça iki kez gelmez."""

    def test_t26_kural_three_different_items_then_no_alternative(self):
        returned = self.swap_until_exhausted(contract("swap-request.json"), replaced_id=1)
        self.assertEqual(len(returned), 3)
        self.assertEqual(set(returned), EXAMPLE_TOP_CANDIDATES)

    def test_t26_ogrenen_three_different_items_then_no_alternative(self):
        body = request_body(method="ogrenen", history=SAMPLE_HISTORY)
        returned = self.swap_until_exhausted(body, replaced_id=1)
        self.assertEqual(len(returned), 3)
        self.assertEqual(set(returned), EXAMPLE_TOP_CANDIDATES)

    def test_t26_ortak_kural_three_different_accessories_then_no_alternative(self):
        body = request_body(method="ortak_kural", targetCategory=None, targetAccessoryId=34,
                            excludedItemIds=[],
                            wardrobe=contract("swap-request.json")["wardrobe"]
                            + [accessory(36, "atki", "sari"), accessory(37, "atki", "mor"),
                               accessory(38, "atki", "lacivert")])
        returned = self.swap_until_exhausted(body, replaced_id=34)
        self.assertEqual(len(returned), 3)
        self.assertEqual(set(returned), {36, 37, 38})


class RuleSwapTests(SwapEndpointTestCase):
    def ust_body(self, excluded):
        # 18 °C, kapalı, günlük: üstte 1, 2, 6, 7 geçer. Kalanlar: kot mavi (10), beyaz spor ayakkabı (17).
        context = {**contract("swap-request.json")["context"], "feelsLikeTemp": 18.0,
                   "weatherCondition": "kapali", "wantsAccessories": False}
        return request_body(context=context, excludedItemIds=excluded,
                            currentOutfit={"template": "ust_alt", "itemIds": [1, 10, 17], "accessoryIds": []})

    def test_kural_picks_best_matching_item_with_remaining_pieces(self):
        # Gri sweatshirt (6) nötr: bütün çiftler yüksek. Pembe bluz (7) mavi kotla düşük puan alır.
        for seed in range(20):
            self.assertEqual(self.new_item_id(self.ust_body([2]), seed), 6)

    def test_current_item_is_never_returned_even_if_not_excluded(self):
        for seed in range(20):
            self.assertNotEqual(self.new_item_id(self.ust_body([]), seed), 1)

    def test_excluded_items_are_never_returned(self):
        self.assertEqual(self.new_item_id(self.ust_body([2, 6])), 7)
        self.assertIsNone(self.new_item_id(self.ust_body([2, 6, 7])))


class CommonFilterTests(SwapEndpointTestCase):
    """Ortak ön filtre E1 ile aynı: sıcaklık, etkinlik, ıslak gün, sıcak gün."""

    def wet_shoe_body(self, current_shoe, wardrobe=None):
        context = {**contract("swap-request.json")["context"], "feelsLikeTemp": 24.0,
                   "weatherCondition": "yagmurlu", "wantsAccessories": False}
        return request_body(context=context, targetCategory="ayakkabi", excludedItemIds=[],
                            currentOutfit={"template": "ust_alt", "itemIds": [1, 10, current_shoe],
                                           "accessoryIds": []},
                            wardrobe=wardrobe or contract("swap-request.json")["wardrobe"])

    def test_exclusion_does_not_relax_wet_rule(self):
        # 24 °C ıslak günde yağmura uygun tek ayakkabı spor ayakkabı (17). O dışlanınca
        # sandalet/babet gelmez: dışlama tekrar engeli gibi en sonda uygulanır.
        self.assertIsNone(self.new_item_id(self.wet_shoe_body(17)))

    def test_wet_fallback_relaxes_like_e1_when_slot_has_no_wet_item(self):
        wardrobe = [i for i in contract("swap-request.json")["wardrobe"] if i["id"] != 17]
        # Kalan günlük ayakkabılar 24 °C'de sandalet (20) ve babet (21); ikisi de ıslakta kaçınılan.
        self.assertEqual(self.new_item_id(self.wet_shoe_body(20, wardrobe)), 21)

    def test_temperature_and_style_filters_apply(self):
        # Örnek bağlamda gömlek (iş/davet), atlet (22 °C üstü) hiç gelmez.
        for seed in range(30):
            self.assertIn(self.new_item_id(contract("swap-request.json"), seed), EXAMPLE_TOP_CANDIDATES)


class LearnedSwapTests(SwapEndpointTestCase):
    def test_model_swap_has_no_exploration(self):
        # Seçilen yorum: değiştirmede %10 keşif yok; eğitilebilen modelde hep en iyi parça.
        body = request_body(method="ogrenen", history=SAMPLE_HISTORY)
        results = {self.new_item_id(body, seed) for seed in range(40)}
        self.assertEqual(len(results), 1)
        self.assertLessEqual(results, EXAMPLE_TOP_CANDIDATES)

    def test_cold_start_picks_a_filtered_candidate(self):
        body = request_body(method="ogrenen", history=[])
        for seed in range(20):
            self.assertIn(self.new_item_id(body, seed), EXAMPLE_TOP_CANDIDATES)


class AccessorySwapTests(SwapEndpointTestCase):
    def accessory_body(self, extra, **changes):
        wardrobe = contract("swap-request.json")["wardrobe"] + extra
        # Dış giyim yok: karşılaştırma parçası pembe bluz (7).
        body = request_body(method="ortak_kural", targetCategory=None, targetAccessoryId=34,
                            excludedItemIds=[], wardrobe=wardrobe,
                            currentOutfit={"template": "ust_alt", "itemIds": [7, 10, 17], "accessoryIds": [34]})
        body.update(changes)
        return body

    def test_next_best_accessory_of_same_subtype(self):
        # Pembe ile mor komşu (yüksek), sarı düşük. Bere başka alt tür: aday değil.
        extra = [accessory(36, "atki", "sari"), accessory(37, "atki", "mor"), accessory(39, "bere", "siyah")]
        for seed in range(10):
            self.assertEqual(self.new_item_id(self.accessory_body(extra), seed), 37)

    def test_t28_accessory_follows_current_state_of_outfit(self):
        # T-28 "değiştirmede o anki hâle göre": üst daha önce sarı tişörtle değiştirildiyse
        # karşılaştırma parçası artık sarı. Sarı-turuncu komşu (yüksek), sarı-mor karşıt (orta).
        yellow_top = {**contract("swap-request.json")["wardrobe"][0], "id": 40, "color": "sari", "tone": "orta"}
        extra = [accessory(36, "atki", "turuncu"), accessory(37, "atki", "mor"), yellow_top]
        pink = self.accessory_body(extra)
        yellow = self.accessory_body(extra, currentOutfit={"template": "ust_alt", "itemIds": [40, 10, 17],
                                                            "accessoryIds": [34]})
        for seed in range(10):
            self.assertEqual(self.new_item_id(pink, seed), 37)
            self.assertEqual(self.new_item_id(yellow, seed), 36)

    def test_only_accessory_of_subtype_gives_no_alternative(self):
        self.assertIsNone(self.new_item_id(self.accessory_body([])))

    def test_accessory_outside_weather_group_gives_no_alternative(self):
        context = {**contract("swap-request.json")["context"], "feelsLikeTemp": 15.0}
        body = self.accessory_body([accessory(36, "atki", "sari")], context=context)
        self.assertIsNone(self.new_item_id(body))


class ValidationTests(SwapEndpointTestCase):
    def test_target_must_match_method(self):
        cases = [
            {"targetCategory": None},                                   # kural ama hedef yok
            {"targetAccessoryId": 34},                                  # kural ama iki hedef
            {"method": "ortak_kural"},                                  # aksesuar yöntemi, kategori hedefi
            {"method": "ortak_kural", "targetCategory": None},          # aksesuar yöntemi, hedef yok
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assert_invalid(self.post(request_body(**changes)))

    def test_target_must_be_in_current_outfit(self):
        self.assert_invalid(self.post(request_body(targetCategory="tek_parca")))
        self.assert_invalid(self.post(request_body(method="ortak_kural", targetCategory=None,
                                                   targetAccessoryId=35)))

    def test_unknown_target_category(self):
        self.assert_invalid(self.post(request_body(targetCategory="aksesuar")))
        self.assert_invalid(self.post(request_body(targetCategory="canta")))

    def test_current_outfit_items_must_be_in_wardrobe(self):
        outfit = {"template": "ust_alt", "itemIds": [1, 10, 17, 99], "accessoryIds": [34]}
        self.assert_invalid(self.post(request_body(currentOutfit=outfit)))

    def test_current_outfit_must_fit_template(self):
        cases = [
            {"template": "tek_parca", "itemIds": [1, 10, 17], "accessoryIds": []},
            {"template": "ust_alt", "itemIds": [1, 2, 10, 17], "accessoryIds": []},  # iki üst
            {"template": "ust_alt", "itemIds": [1, 10, 17, 34], "accessoryIds": []},  # aksesuar ana parçada
            {"template": "ust_alt", "itemIds": [1, 10, 17], "accessoryIds": [24]},    # mont aksesuarda
        ]
        for outfit in cases:
            with self.subTest(outfit=outfit):
                self.assert_invalid(self.post(request_body(currentOutfit=outfit)))

    def test_history_only_with_ogrenen(self):
        self.assert_invalid(self.post(request_body(history=SAMPLE_HISTORY)))
        self.assert_invalid(self.post(request_body(method="ortak_kural", targetCategory=None,
                                                   targetAccessoryId=34, history=SAMPLE_HISTORY)))

    def test_strict_fields(self):
        self.assert_invalid(self.post(request_body(method="rastgele")))
        self.assert_invalid(self.post(request_body(extra=1)))
        self.assert_invalid(self.post(request_body(excludedItemIds=["5"])))
        self.assert_invalid(self.post(request_body(excludedItemIds=[0])))
        self.assert_invalid(self.post(b"{bozuk"))

    def test_null_targets_may_be_omitted(self):
        body = request_body()
        del body["targetAccessoryId"]
        self.assertIn(self.new_item_id(body), EXAMPLE_TOP_CANDIDATES)


if __name__ == "__main__":
    unittest.main()

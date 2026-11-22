"""E7: POST /recommend ucu.

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

from recommendation import recommend as recommend_module
from recommendation import router as router_module
from recommendation.models import Weather, load_wardrobe
from recommendation.recommend import recommend
from service.main import create_app

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "tests" / "contracts"
USER_ID = "178eaf32-7cf1-4399-8957-6532e4c7fc91"
PICK_MODES = {"soguk_baslangic", "kesif", "model"}


def contract(name):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def camel(name):
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def item_json(row):
    return {camel(key): value for key, value in row.items()}


def local_history_as_contract(rows):
    """tests/sample_history.json (yerel biçim) → A3 history kayıtları."""
    def outfit(value):
        if value is None:
            return None
        return {"template": value["template"], "items": [item_json(i) for i in value["items"]]}

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


SAMPLE_WARDROBE = [item_json(row) for row in
                   json.loads((ROOT / "tests" / "sample_wardrobe.json").read_text(encoding="utf-8"))]
SAMPLE_HISTORY = local_history_as_contract(
    json.loads((ROOT / "tests" / "sample_history.json").read_text(encoding="utf-8")))


def wardrobe_by_ids(*ids):
    return [copy.deepcopy(i) for i in SAMPLE_WARDROBE if i["id"] in ids]


def request_body(**changes):
    body = contract("recommend-request.json")
    body.update(changes)
    return body


class RecommendEndpointTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.seed = 42
        self.app.dependency_overrides[router_module.get_rng] = lambda: random.Random(self.seed)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def post(self, body, seed=None):
        if seed is not None:
            self.seed = seed
        payload = body if isinstance(body, (bytes, str)) else json.dumps(body)
        return self.client.post("/recommend", content=payload,
                                headers={"Content-Type": "application/json"})

    def assert_invalid(self, response):
        self.assertEqual(response.status_code, 422, response.text)
        body = response.json()
        self.assertEqual(set(body), {"code", "message"})
        self.assertEqual(body["code"], "invalid_request")
        self.assertIsInstance(body["message"], str)
        self.assertTrue(body["message"])


class ContractTests(RecommendEndpointTestCase):
    """Sözleşme örnekleriyle alan alan biçim testleri."""

    def assert_same_shape(self, actual, example):
        self.assertEqual(set(actual), set(example))
        for key in ("ruleOutfit", "learnedOutfit"):
            self.assertEqual(set(actual[key]), set(example[key]))
            self.assertIn(actual[key]["template"], {"ust_alt", "tek_parca"})
            self.assertTrue(actual[key]["itemIds"])
            self.assertTrue(all(type(i) is int for i in actual[key]["itemIds"]))
        self.assertIs(type(actual["isSameOutfit"]), bool)
        self.assertIn(actual["learnedPickMode"], PICK_MODES)
        self.assertTrue(all(type(i) is int for i in actual["accessoryIds"]))

    def test_example_request_gets_response_in_contract_shape(self):
        response = self.post(contract("recommend-request.json"))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assert_same_shape(body, contract("recommend-response.json"))
        self.assertEqual(body["status"], "ok")

        wardrobe = {i["id"]: i for i in contract("recommend-request.json")["wardrobe"]}
        for key in ("ruleOutfit", "learnedOutfit"):
            items = [wardrobe[i] for i in body[key]["itemIds"]]
            self.assertFalse(any(i["category"] == "aksesuar" for i in items))
            self.assertEqual(body[key]["template"],
                             "tek_parca" if any(i["category"] == "tek_parca" for i in items) else "ust_alt")
        # Örnek bağlam 9,4 °C, akşam, aksesuar isteniyor; dolapta yalnız gri atkı (#34) var.
        self.assertEqual(body["accessoryIds"], [34])
        # Örnek geçmişte 3 karar var: soğuk başlangıç (T-32).
        self.assertEqual(body["learnedPickMode"], "soguk_baslangic")
        self.assertEqual(body["isSameOutfit"], body["ruleOutfit"] == body["learnedOutfit"])

    def test_same_outfit_shape(self):
        # Tek olası kombin: iki yöntem aynı kombini seçer.
        body = request_body(wardrobe=wardrobe_by_ids(1, 10, 17, 34),
                            context={**contract("recommend-request.json")["context"],
                                     "feelsLikeTemp": 18.0, "weatherCondition": "kapali",
                                     "wantsAccessories": False},
                            history=[])
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.text)
        actual = response.json()
        self.assert_same_shape(actual, contract("recommend-response-same-outfit.json"))
        self.assertTrue(actual["isSameOutfit"])
        self.assertEqual(actual["ruleOutfit"], actual["learnedOutfit"])
        self.assertEqual(actual["ruleOutfit"], {"template": "ust_alt", "itemIds": [1, 10, 17]})
        self.assertEqual(actual["accessoryIds"], [])

    def test_no_candidates_matches_example_exactly(self):
        body = request_body(context={**contract("recommend-request.json")["context"], "feelsLikeTemp": 50.0})
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), contract("recommend-response-no-candidates.json"))

    def test_no_candidates_without_shoes(self):
        body = request_body(wardrobe=[i for i in contract("recommend-request.json")["wardrobe"]
                                      if i["category"] != "ayakkabi"])
        self.assertEqual(self.post(body).json(), {"status": "no_candidates"})

    def test_internal_error_shape(self):
        with mock.patch.object(router_module, "recommend", side_effect=RuntimeError("bozuk")), \
                self.assertLogs("recommendation.router", level="ERROR"):
            response = self.post(contract("recommend-request.json"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), contract("error.json"))

    def test_router_is_mounted(self):
        self.assertIn("recommendation", self.client.get("/health").json()["modules"])


class BehaviourTests(RecommendEndpointTestCase):
    def test_t24_rejected_outfit_is_not_proposed_again(self):
        # İki olası kombin: [1, 10, 17] ve [2, 10, 17]. İlki reddedildi.
        base = request_body(wardrobe=wardrobe_by_ids(1, 2, 10, 17),
                            context={**contract("recommend-request.json")["context"],
                                     "feelsLikeTemp": 18.0, "weatherCondition": "kapali"},
                            history=[])
        for seed in range(10):
            with self.subTest(seed=seed):
                body = self.post({**base, "rejectedOutfits": [[17, 10, 1]]}, seed=seed).json()
                self.assertEqual(body["ruleOutfit"]["itemIds"], [2, 10, 17])
                self.assertEqual(body["learnedOutfit"]["itemIds"], [2, 10, 17])
                self.assertTrue(body["isSameOutfit"])
        everything = self.post({**base, "rejectedOutfits": [[1, 10, 17], [2, 10, 17]]})
        self.assertEqual(everything.json(), {"status": "no_candidates"})

    def test_t32_cold_start_through_endpoint(self):
        for count in (0, 9):
            with self.subTest(decisions=count):
                response = self.post(request_body(wardrobe=SAMPLE_WARDROBE, history=SAMPLE_HISTORY[:count]))
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["learnedPickMode"], "soguk_baslangic")

    def test_t33_exploration_and_model_through_endpoint(self):
        # 12 sentetik karar, iki sınıf: tohuma göre %10 keşif, diğer durumda model.
        body = request_body(wardrobe=SAMPLE_WARDROBE, history=SAMPLE_HISTORY)
        modes = {self.post(body, seed=seed).json()["learnedPickMode"] for seed in range(60)}
        self.assertEqual(modes, {"kesif", "model"})

    def test_same_seed_gives_same_response(self):
        body = request_body(wardrobe=SAMPLE_WARDROBE, history=SAMPLE_HISTORY)
        self.assertEqual(self.post(body, seed=5).json(), self.post(body, seed=5).json())

    def test_wants_accessories_false_gives_empty_list(self):
        body = request_body(context={**contract("recommend-request.json")["context"],
                                     "wantsAccessories": False})
        self.assertEqual(self.post(body).json()["accessoryIds"], [])

    def test_hat_on_given_sunny_noon(self):
        # Elle verilen hava: 28 °C, güneşli, öğle.
        body = request_body(context={"feelsLikeTemp": 28.0, "weatherCondition": "gunesli",
                                     "timeOfDay": "ogle", "isDaytime": True, "eventStyle": "gunluk",
                                     "wantsAccessories": True})
        self.assertEqual(self.post(body).json()["accessoryIds"], [35])

    def test_deleted_items_in_history_are_accepted(self):
        body = request_body()
        body["history"][0]["ruleOutfit"]["items"][0]["status"] = "silindi"
        self.assertEqual(self.post(body).status_code, 200)


class InvalidRequestTests(RecommendEndpointTestCase):
    def test_unknown_history_result_key(self):
        for key in ("KS", "OS", "AT", "BK", "TP", "XX"):
            with self.subTest(key=key):
                body = request_body()
                body["history"][0]["resultKey"] = key
                self.assert_invalid(self.post(body))

    def test_unknown_codes(self):
        cases = {
            "subtype": ("wardrobe", 0, "subtype", "kravat"),
            "color": ("wardrobe", 0, "color", "bordo"),
            "category_mismatch": ("wardrobe", 0, "category", "alt"),
            "status": ("wardrobe", 0, "status", "kayip"),
        }
        for name, (section, index, field, value) in cases.items():
            with self.subTest(name=name):
                body = request_body()
                body[section][index][field] = value
                self.assert_invalid(self.post(body))
        for field, value in (("weatherCondition", "dolu"), ("eventStyle", "parti"), ("timeOfDay", "ikindi")):
            with self.subTest(field=field):
                body = request_body()
                body["context"][field] = value
                self.assert_invalid(self.post(body))

    def test_missing_extra_and_wrong_typed_fields(self):
        body = request_body()
        del body["context"]["isDaytime"]
        self.assert_invalid(self.post(body))
        body = request_body(extra=1)
        self.assert_invalid(self.post(body))
        body = request_body()
        body["context"]["wantsAccessories"] = "true"
        self.assert_invalid(self.post(body))
        body = request_body()
        body["wardrobe"][0]["id"] = "1"
        self.assert_invalid(self.post(body))
        body = request_body(userId="demo")
        self.assert_invalid(self.post(body))

    def test_malformed_json_and_non_object(self):
        self.assert_invalid(self.post(b"{bozuk"))
        self.assert_invalid(self.post("[]"))
        self.assert_invalid(self.post(""))

    def test_duplicates_and_bad_rejected_outfits(self):
        body = request_body()
        body["wardrobe"].append(copy.deepcopy(body["wardrobe"][0]))
        self.assert_invalid(self.post(body))
        body = request_body()
        body["history"][1]["comparisonId"] = body["history"][0]["comparisonId"]
        self.assert_invalid(self.post(body))
        for rejected in ([[1, 1, 17]], [[0, 10]], [[]]):
            with self.subTest(rejected=rejected):
                self.assert_invalid(self.post(request_body(rejectedOutfits=rejected)))

    def test_history_rules_from_e4_are_enforced(self):
        body = request_body()
        body["history"][1]["finalOutfit"] = None  # OD için son kombin gerekli.
        self.assert_invalid(self.post(body))
        body = request_body()
        body["history"][0]["completedAt"] = "2026-11-23T07:42:10"  # Saat dilimi yok.
        self.assert_invalid(self.post(body))

    def test_fastapi_detail_format_is_never_returned(self):
        response = self.post(request_body(context=None))
        self.assert_invalid(response)
        self.assertNotIn("detail", response.json())


class RecommendFunctionTests(unittest.TestCase):
    """Uçtan bağımsız akış: E1 bir kez, E2 ve E4 aynı havuzdan, E6 tek liste."""

    def setUp(self):
        self.wardrobe = load_wardrobe(ROOT / "tests" / "sample_wardrobe.json")

    def run_recommend(self, **changes):
        values = dict(wardrobe=self.wardrobe, weather=Weather(9.4, "yagmurlu"), style="gunluk",
                      is_daytime=False, wants_accessories=True, rejected_outfits=(), history=(),
                      user_id=USER_ID, rng=random.Random(42))
        values.update(changes)
        return recommend(**values)

    def test_candidate_pool_is_generated_once(self):
        with mock.patch.object(recommend_module, "generate_candidates",
                               wraps=recommend_module.generate_candidates) as spy:
            result = self.run_recommend()
        self.assertEqual(spy.call_count, 1)
        self.assertIsNotNone(result)

    def test_both_cards_come_from_the_same_pool(self):
        captured = {}
        original = recommend_module.generate_candidates

        def capture(*args, **kwargs):
            captured["pool"] = original(*args, **kwargs)
            return captured["pool"]

        with mock.patch.object(recommend_module, "generate_candidates", side_effect=capture):
            result = self.run_recommend()
        keys = {outfit.key for outfit in captured["pool"].candidates}
        assert result is not None
        self.assertIn(result.rule_outfit.key, keys)
        self.assertIn(result.learned_outfit.key, keys)

    def test_accessories_use_one_card_when_outfits_are_same(self):
        calls = []
        original = recommend_module.select_accessories

        def capture(cards, *args, **kwargs):
            calls.append(len(cards))
            return original(cards, *args, **kwargs)

        only_one_outfit = tuple(i for i in self.wardrobe if i.id in (1, 10, 17, 34))
        with mock.patch.object(recommend_module, "select_accessories", side_effect=capture):
            different = self.run_recommend()
            same = self.run_recommend(wardrobe=only_one_outfit, weather=Weather(18, "kapali"))
        assert different is not None and same is not None
        self.assertFalse(different.is_same_outfit)
        self.assertTrue(same.is_same_outfit)
        self.assertEqual(calls, [2, 1])

    def test_returns_none_without_candidates(self):
        self.assertIsNone(self.run_recommend(weather=Weather(50, "gunesli")))


if __name__ == "__main__":
    unittest.main()

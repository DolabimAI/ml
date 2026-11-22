import io
import unittest
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from service.main import create_app
from vision import router as vision_router
from vision import storage
from vision.subtype import SubtypePredictor, load_subtype_settings

USER = "178eaf32-7cf1-4399-8957-6532e4c7fc91"
# DolabimAI/api contracts/examples/analyze-response.json ile aynı alanlar
EXAMPLE_KEYS = {"imagePath", "subtype", "subtypeConfidence", "color", "tone", "isPatterned", "rawColor"}


class FakeEmbedder:
    """Her etiket için ayrı bir birim vektör; görsel her zaman `target` etiketine yakın."""

    logit_scale = 100.0

    def __init__(self, target="gomlek"):
        self.settings = load_subtype_settings()
        self.keys = list(self.settings["labels"])
        self.target = target

    def encode_texts(self, texts):
        return np.eye(len(texts))

    def encode_image(self, image):
        v = np.zeros(len(self.keys))
        v[self.keys.index(self.target)] = 1.0
        return v


def png_bytes(color=(60, 90, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


def fake_remove_background(img, settings=None):
    rgba = img.convert("RGBA")
    return rgba  # tamamen opak: bütün pikseller kıyafet sayılır


class AnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.uploaded = []
        self.deleted = []
        patches = [
            mock.patch.object(vision_router, "get_predictor", lambda: SubtypePredictor(FakeEmbedder())),
            mock.patch("vision.background.remove_background", fake_remove_background),
            mock.patch.object(storage, "upload_webp", self._upload),
            mock.patch.object(storage, "delete_object", lambda path, **kw: self.deleted.append(path)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _upload(self, data, user_id, **kw):
        path = storage.build_path(user_id)
        self.uploaded.append((path, len(data)))
        return path

    def post(self, data=None, user_id=USER):
        files = {"image": ("foto.png", png_bytes() if data is None else data, "image/png")}
        return self.client.post("/analyze", files=files, data={"userId": user_id})

    def test_success_shape_matches_contract(self):
        r = self.post()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), EXAMPLE_KEYS)
        self.assertEqual(body["subtype"], "gomlek")
        self.assertRegex(body["imagePath"], rf"^{USER}/[0-9a-f]{{32}}\.webp$")
        self.assertRegex(body["rawColor"], r"^#[0-9A-F]{6}$")
        self.assertIn(body["tone"], {"acik", "orta", "koyu"})
        self.assertIsInstance(body["isPatterned"], bool)
        self.assertEqual(body["subtypeConfidence"], round(body["subtypeConfidence"], 3))
        self.assertLessEqual(self.uploaded[0][1], 1_000_000)
        self.assertEqual(self.deleted, [])

    def test_blue_photo_color(self):
        self.assertEqual(self.post().json()["color"], "mavi")

    def test_low_confidence_still_returns_top_subtype(self):
        class Flat(FakeEmbedder):
            def encode_image(self, image):
                return np.ones(len(self.keys))  # bütün etiketlere eşit uzaklık

        with mock.patch.object(vision_router, "get_predictor", lambda: SubtypePredictor(Flat())):
            body = self.post().json()
        self.assertIn(body["subtype"], load_subtype_settings()["labels"])
        self.assertLess(body["subtypeConfidence"], 0.40)

    def test_unreadable_image_is_422_and_writes_nothing(self):
        r = self.post(b"bu bir fotograf degil")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["code"], "image_unreadable")
        self.assertEqual(set(r.json()), {"code", "message"})
        self.assertEqual(self.uploaded, [])

    def test_invalid_user_id_is_invalid_request(self):
        r = self.post(user_id="../x")
        self.assertEqual((r.status_code, r.json()["code"]), (422, "invalid_request"))
        self.assertEqual(self.uploaded, [])

    def test_missing_fields_are_invalid_request(self):
        r = self.client.post("/analyze", data={"userId": USER})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "invalid_request"))
        self.assertEqual(set(r.json()), {"code", "message"})

    def test_failure_after_upload_deletes_image_and_returns_500(self):
        class Broken:
            def predict(self, image):
                raise RuntimeError("model çöktü")

        client = TestClient(create_app(), raise_server_exceptions=False)
        with mock.patch.object(vision_router, "get_predictor", lambda: Broken()):
            r = client.post("/analyze", files={"image": ("f.png", png_bytes(), "image/png")}, data={"userId": USER})
        self.assertEqual((r.status_code, r.json()["code"]), (500, "internal_error"))
        self.assertEqual(self.deleted, [self.uploaded[0][0]])

    def test_storage_failure_is_500_without_delete(self):
        client = TestClient(create_app(), raise_server_exceptions=False)
        with mock.patch.object(storage, "upload_webp", side_effect=storage.StorageError("x")):
            r = client.post("/analyze", files={"image": ("f.png", png_bytes(), "image/png")}, data={"userId": USER})
        self.assertEqual((r.status_code, r.json()["code"]), (500, "internal_error"))
        self.assertEqual(self.deleted, [])


class DeleteTest(unittest.TestCase):
    def test_delete_request(self):
        import httpx

        seen = {}

        def handler(request):
            seen["method"], seen["url"] = request.method, str(request.url)
            return httpx.Response(200, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        storage.delete_object(f"{USER}/a.webp", supabase_url="https://x.supabase.co", service_key="k",
                              bucket="gorseller", client=client)
        self.assertEqual(seen["method"], "DELETE")
        self.assertEqual(seen["url"], f"https://x.supabase.co/storage/v1/object/gorseller/{USER}/a.webp")


if __name__ == "__main__":
    unittest.main()

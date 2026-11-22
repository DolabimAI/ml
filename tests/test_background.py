import io
import json
import os
import unittest

import httpx
import numpy as np
from PIL import Image, ImageDraw

from vision import background as bg
from vision import storage

S = bg.load_image_settings()


def noisy_rgba(side=2400):
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 255, size=(side, side, 4), dtype=np.uint8)
    arr[..., 3] = 255
    arr[: side // 2, :, 3] = 0
    return Image.fromarray(arr, "RGBA")


class ShrinkTest(unittest.TestCase):
    def test_noisy_image_ends_under_300kb_and_keeps_alpha(self):
        data, size = bg.shrink_to_webp(noisy_rgba(), S)
        self.assertLessEqual(len(data), S["target_max_bytes"])
        self.assertLessEqual(max(size), S["max_side_px"])
        img = Image.open(io.BytesIO(data))
        self.assertEqual(img.format, "WEBP")
        self.assertEqual(img.convert("RGBA").getchannel("A").getextrema()[0], 0)

    def test_mask_uses_only_opaque_pixels(self):
        img = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
        ImageDraw.Draw(img).rectangle((20, 20, 79, 79), fill=(10, 20, 200, 255))
        px = bg.clothing_pixels(img, S)
        self.assertEqual(px.shape, (3600, 3))
        self.assertTrue((px == [10, 20, 200]).all())

    def test_empty_mask_raises(self):
        with self.assertRaises(bg.ImageError):
            bg.clothing_pixels(Image.new("RGBA", (50, 50), (0, 0, 0, 0)), S)

    def test_large_mask_is_subsampled_deterministically(self):
        img = Image.new("RGBA", (400, 400), (1, 2, 3, 255))
        a, b = bg.clothing_pixels(img, S), bg.clothing_pixels(img, S)
        self.assertLessEqual(len(a), S["mask_max_pixels"])
        self.assertTrue((a == b).all())

    def test_corrupt_file_raises(self):
        with self.assertRaises(bg.ImageError):
            bg.open_image(b"bu bir resim degil")


class StorageTest(unittest.TestCase):
    def _client(self, status=200):
        seen = {}

        def handler(request: httpx.Request):
            seen["url"], seen["headers"], seen["body"] = str(request.url), request.headers, request.content
            return httpx.Response(status, json={})

        return httpx.Client(transport=httpx.MockTransport(handler)), seen

    def test_upload_path_and_request(self):
        client, seen = self._client()
        path = storage.upload_webp(b"webp", "user-123", supabase_url="https://x.supabase.co/",
                                   service_key="k", bucket="gorseller", client=client)
        self.assertRegex(path, r"^user-123/[0-9a-f]{32}\.webp$")
        self.assertEqual(seen["url"], f"https://x.supabase.co/storage/v1/object/gorseller/{path}")
        self.assertEqual(seen["headers"]["content-type"], "image/webp")
        self.assertEqual(seen["body"], b"webp")

    def test_unsafe_user_id_is_rejected(self):
        for bad in ("../x", "a/b", "", "a b"):
            with self.assertRaises(ValueError):
                storage.build_path(bad)

    def test_failed_upload_raises(self):
        client, _ = self._client(403)
        with self.assertRaises(storage.StorageError):
            storage.upload_webp(b"x", "u1", supabase_url="https://x", service_key="k",
                                bucket="gorseller", client=client)

    def test_missing_settings_raise(self):
        with self.assertRaises(storage.StorageError):
            storage.upload_webp(b"x", "u1", supabase_url="", service_key="", bucket="gorseller")


@unittest.skipUnless(os.environ.get("ML_RUN_MODEL_TESTS") == "1",
                     "arka plan modeli testi için ML_RUN_MODEL_TESTS=1 (u2net ~176 MB indirir)")
class ModelTest(unittest.TestCase):
    def test_synthetic_garment_gets_transparent_background(self):
        img = Image.new("RGB", (400, 400), (235, 235, 235))
        ImageDraw.Draw(img).rectangle((110, 80, 290, 330), fill=(30, 60, 200))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        out = bg.process_image(buf.getvalue(), S)
        rgba = Image.open(io.BytesIO(out.webp)).convert("RGBA")
        self.assertEqual(rgba.getchannel("A").getextrema()[0], 0)
        self.assertLessEqual(len(out.webp), S["target_max_bytes"])
        self.assertGreater(len(out.pixels), 1000)


if __name__ == "__main__":
    unittest.main()

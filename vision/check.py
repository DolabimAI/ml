"""D3: 20 kontrol fotoğrafında alt tür ve renk kontrolü.

Kullanım (depo kökünden):
  python -m vision.check --photos klasor --labels etiketler.csv --out sonuc.csv
  python -m vision.check --photos klasor --labels etiketler.csv --skip-subtype   # yalnız renk

etiketler.csv sütunları: dosya,alt_tur,renk  (elle yazılan doğrular, ortak kod listesi value kodlarıyla).
Sonuçlar ayar içindir; tezde başarı ölçüsü olarak kullanılmaz (doğruluk, çalışmadaki kullanıcı
düzeltmelerinden ölçülür).
"""
from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path


def evaluate(rows: list[dict]) -> dict:
    """rows: dosya, alt_tur (doğru), renk (doğru), tahmin_alt_tur, tahmin_renk, sure_sn.
    tahmin_alt_tur boş olabilir (güven eşiği altı); en yüksek tahmin 'en_yuksek_alt_tur' alanındadır."""
    n = len(rows)
    sub = [r for r in rows if r.get("tahmin_alt_tur") is not None or r.get("en_yuksek_alt_tur")]
    sub_ok = sum(1 for r in rows if r.get("en_yuksek_alt_tur") == r["alt_tur"])
    sub_ok_thresholded = sum(1 for r in rows if r.get("tahmin_alt_tur") == r["alt_tur"])
    color_ok = sum(1 for r in rows if r.get("tahmin_renk") == r["renk"])
    times = [r["sure_sn"] for r in rows if r.get("sure_sn") is not None]
    return {
        "foto_sayisi": n,
        "alt_tur_dogru_en_yuksek": sub_ok if sub else None,
        "alt_tur_dogru_esik_sonrasi": sub_ok_thresholded if sub else None,
        "renk_dogru": color_ok,
        "ortalama_sure_sn": round(sum(times) / len(times), 2) if times else None,
        "yanlis_alt_tur": [r["dosya"] for r in rows if sub and r.get("en_yuksek_alt_tur") != r["alt_tur"]],
        "yanlis_renk": [r["dosya"] for r in rows if r.get("tahmin_renk") != r["renk"]],
    }


def run(photos: Path, labels: Path, skip_subtype: bool) -> list[dict]:
    from vision.background import open_image, process_image
    from vision.color import extract_color

    predictor = None
    if not skip_subtype:
        from vision.subtype import FashionClipEmbedder, SubtypePredictor

        predictor = SubtypePredictor(FashionClipEmbedder())

    rows = []
    with labels.open(encoding="utf-8", newline="") as f:
        for rec in csv.DictReader(f):
            data = (photos / rec["dosya"]).read_bytes()
            t0 = time.perf_counter()
            out = process_image(data)
            color = extract_color(out.pixels)
            row = {**rec, "tahmin_renk": color.color, "tahmin_ton": color.tone, "desenli": color.is_patterned}
            if predictor:
                p = predictor.predict(open_image(data))
                row.update(tahmin_alt_tur=p.subtype, en_yuksek_alt_tur=p.top_subtype, guven=round(p.confidence, 3))
            row["sure_sn"] = round(time.perf_counter() - t0, 2)
            rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photos", type=Path, required=True)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--skip-subtype", action="store_true")
    a = ap.parse_args()
    rows = run(a.photos, a.labels, a.skip_subtype)
    for k, v in evaluate(rows).items():
        print(f"{k}: {v}")
    if a.out:
        keys = sorted({k for r in rows for k in r})
        with a.out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()

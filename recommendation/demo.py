"""E1 aday demosu; E2 Kural Kartı için --method rule eklenir."""

import argparse
import random
from pathlib import Path

from .filter import generate_candidates
from .models import Weather, load_catalog, load_wardrobe
from .rule_based import select_rule_outfit


def main() -> None:
    parser = argparse.ArgumentParser(description="DolabımAI aday havuzu ve Kural Kartı demosu")
    parser.add_argument("--method", choices=("candidates", "rule"), default="candidates")
    parser.add_argument("--temperature", type=float, default=24)
    parser.add_argument("--weather", choices=[w["value"] for w in load_catalog()["weather_conditions"]],
                        default="yagmurlu")
    parser.add_argument("--style", choices=load_catalog()["styles"], default="gunluk")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--wardrobe", type=Path,
                        default=Path(__file__).resolve().parents[1] / "tests" / "sample_wardrobe.json")
    args = parser.parse_args()
    pool = generate_candidates(load_wardrobe(args.wardrobe), Weather(args.temperature, args.weather),
                               args.style, rng=random.Random(args.seed))
    print(f"Hissedilen: {args.temperature:g} °C | Hava: {args.weather} | Etkinlik: {args.style}")
    print(f"Aday sayısı: {len(pool.candidates)} | Aday sınırına ulaşıldı: {pool.limit_reached}")
    print(f"Yedek uygulanan konumlar: {', '.join(pool.fallback_slots) or 'yok'}")
    for outfit in pool.candidates[:5]:
        print(f"{outfit.template}: " + " + ".join(f"{i.subtype}#{i.id}" for i in outfit.items))
    if not pool.candidates:
        print("Bu bağlamda uygun kombin bulunamadı.")
    if args.method == "rule":
        selection = select_rule_outfit(pool.candidates, rng=random.Random(args.seed))
        if selection is None:
            print("Kural Kartı üretilemedi: uygun aday yok.")
            return
        print(f"\nKural Kartı ({selection.outfit.template}):")
        for item in selection.outfit.items:
            print(f"  {item.subtype}#{item.id}: {item.color} / {item.tone}")
        score = selection.score
        print(f"Çift puanı ortalaması: {score.pair_average:.3f}")
        print(f"Farklı canlı renk: {score.vivid_color_count} | Ceza: {score.penalty:.3f}")
        print(f"Kural puanı: {score.total:.3f} | En yüksek puanda eşit aday: {selection.tied_best_count}")


if __name__ == "__main__":
    main()

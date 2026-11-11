"""E1'i örnek dolapla terminalde denemek için: python -m recommendation.demo."""

import argparse
import random
from pathlib import Path

from .filter import generate_candidates
from .models import Weather, load_catalog, load_wardrobe


def main() -> None:
    parser = argparse.ArgumentParser(description="DolabımAI E1 aday havuzu demosu")
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


if __name__ == "__main__":
    main()

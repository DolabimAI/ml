"""E1 adayları, E2/E4 kartları ve E3 özellik vektörü için terminal demosu."""

import argparse
import random
from pathlib import Path

from .features import FEATURE_SCHEMA_VERSION, encode_outfits, feature_names
from .filter import generate_candidates
from .models import Weather, load_catalog, load_wardrobe
from .rule_based import select_rule_outfit


def main() -> None:
    parser = argparse.ArgumentParser(description="DolabımAI aday, kart ve özellik vektörü demosu")
    parser.add_argument("--method", choices=("candidates", "rule", "features", "learned"), default="candidates")
    parser.add_argument("--history", type=Path, help="Yerel karşılaştırma geçmişi JSON'u")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--temperature", type=float, default=24)
    parser.add_argument("--weather", choices=[w["value"] for w in load_catalog()["weather_conditions"]],
                        default="yagmurlu")
    parser.add_argument("--style", choices=load_catalog()["styles"], default="gunluk")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--wardrobe", type=Path,
                        default=Path(__file__).resolve().parents[1] / "tests" / "sample_wardrobe.json")
    args = parser.parse_args()
    weather = Weather(args.temperature, args.weather)
    pool = generate_candidates(load_wardrobe(args.wardrobe), weather,
                               args.style, rng=random.Random(args.seed))
    print(f"Hissedilen: {args.temperature:g} °C | Hava: {args.weather} | Etkinlik: {args.style}")
    print(f"Aday sayısı: {len(pool.candidates)} | Aday sınırına ulaşıldı: {pool.limit_reached}")
    print(f"Yedek uygulanan konumlar: {', '.join(pool.fallback_slots) or 'yok'}")
    for outfit in pool.candidates[:5]:
        print(f"{outfit.template}: " + " + ".join(f"{i.subtype}#{i.id}" for i in outfit.items))
    if not pool.candidates:
        print("Bu bağlamda uygun kombin bulunamadı.")
    if args.method == "features":
        names = feature_names()
        vectors = encode_outfits(pool.candidates, weather, args.style)
        print(f"\nÖzellik şeması: {FEATURE_SCHEMA_VERSION} | Vektör boyutu: {len(names)}")
        print(f"Kodlanan aday sayısı: {len(vectors)}")
        if not vectors:
            print("Özellik vektörü üretilemedi: uygun aday yok.")
            return
        print("İlk adayın sıfırdan farklı özellikleri:")
        for name, value in zip(names, vectors[0], strict=True):
            if value != 0:
                print(f"  {name}: {value:g}")
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
    if args.method == "learned":
        # E1/E2/E3 demoları scikit-learn kurulmadan da çalışabilsin.
        from .history import load_history
        from .learned import select_learned_outfit

        history = load_history(args.history) if args.history is not None else ()
        learned = select_learned_outfit(pool.candidates, weather, args.style, history,
                                       user_id=args.user_id, rng=random.Random(args.seed))
        if learned is None:
            print("Öğrenen Kart üretilemedi: uygun aday yok.")
            return
        print(f"\nÖğrenen Kart ({learned.outfit.template}):")
        for item in learned.outfit.items:
            print(f"  {item.subtype}#{item.id}: {item.color} / {item.tone}")
        print(f"Öğrenen modu: {learned.ogrenen_mode}")
        if learned.reason is not None:
            print(f"Rastgele seçim nedeni: {learned.reason}")
        print(f"Geçerli karar: {learned.decision_count} | Kural kararı: {learned.rule_decision_count}")
        print(f"Pozitif örnek: {learned.positive_count} | Negatif örnek: {learned.negative_count}")
        if learned.probability is not None:
            print(f"Model olasılığı P(y=1): {learned.probability:.6f}")


if __name__ == "__main__":
    main()

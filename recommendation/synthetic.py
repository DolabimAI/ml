"""E10: ekransız sentetik kullanıcı testi.

Bir profil, aynı E1 havuzundan seçilen Kural ve Öğrenen kartları kendi zevk kuralıyla
karşılaştırır; karar E4'ün bir sonraki çağrısına geçmiş olarak verilir. Sonuçlar
SENTETİKTİR: gerçek kullanıcı tercihi veya kullanıcı çalışması bulgusu değildir.
"""

import argparse
import csv
import json
import math
import random
import statistics
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from .filter import Outfit, generate_candidates
from .history import RESULT_STATUSES, ComparisonDecision, main_outfit_key
from .learned import LearnedSettings, select_learned_outfit
from .models import ClothingItem, FilterSettings, Weather, load_catalog, load_wardrobe
from .rule_based import RuleSettings, select_rule_outfit

_PACKAGE = Path(__file__).parent
_START = datetime(2026, 12, 7, 9, tzinfo=timezone.utc)
_RNG_STREAMS = ("baglam", "aday", "kural", "ogrenen", "profil")


def _is_number(value) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _code_tuple(value, catalog_name: str, field_name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple) or not value or len(value) != len(set(value)):
        raise ValueError(f"{field_name} boş olmayan, tekrarsız bir tuple ya da None olmalı")
    unknown = set(value) - set(load_catalog()[catalog_name])
    if unknown:
        raise ValueError(f"{field_name} bilinmeyen kod içeriyor: {', '.join(sorted(unknown))}")
    return value


@dataclass(frozen=True)
class SyntheticProfile:
    """Parça düzeyinde zevk kuralı; None olan koşul o özelliği önemsemez."""

    profile_id: str
    description: str
    liked_colors: tuple[str, ...] | None
    liked_tones: tuple[str, ...] | None
    liked_patterned: bool | None
    accept_threshold: float

    def __post_init__(self) -> None:
        for name in ("profile_id", "description"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} boş olmayan bir metin olmalı")
        _code_tuple(self.liked_colors, "colors", "liked_colors")
        _code_tuple(self.liked_tones, "tones", "liked_tones")
        if self.liked_patterned is not None and not isinstance(self.liked_patterned, bool):
            raise ValueError("liked_patterned true, false ya da null olmalı")
        if self.liked_colors is None and self.liked_tones is None and self.liked_patterned is None:
            raise ValueError("Profil en az bir zevk koşulu içermeli")
        if not _is_number(self.accept_threshold) or not 0 <= self.accept_threshold <= 1:
            raise ValueError("accept_threshold [0, 1] aralığında bir sayı olmalı")

    def item_matches(self, item: ClothingItem) -> bool:
        return ((self.liked_colors is None or item.color in self.liked_colors)
                and (self.liked_tones is None or item.tone in self.liked_tones)
                and (self.liked_patterned is None or item.is_patterned == self.liked_patterned))

    def utility(self, outfit: Outfit) -> float:
        """Ana parçaların (dış giyim dahil, aksesuar hariç) profile uyan payı."""
        main = [item for item in outfit.items if item.category != "aksesuar"]
        if not main:
            raise ValueError("Profil uyumu için en az bir ana parça gerekli")
        return sum(self.item_matches(item) for item in main) / len(main)


def load_profiles(path: str | Path | None = None) -> dict[str, SyntheticProfile]:
    source = Path(path) if path is not None else _PACKAGE / "synthetic_profiles.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError("Profil dosyası boş olmayan bir nesne olmalı")
    expected = {f.name for f in fields(SyntheticProfile)} - {"profile_id"}
    profiles = {}
    for profile_id, row in data.items():
        if not isinstance(row, dict) or set(row) != expected:
            raise ValueError(f"{profile_id} profilinde eksik veya bilinmeyen alan var")
        values = dict(row)
        for name in ("liked_colors", "liked_tones"):
            if values[name] is not None:
                if not isinstance(values[name], list):
                    raise ValueError(f"JSON {name} liste ya da null olmalı")
                values[name] = tuple(values[name])
        profiles[profile_id] = SyntheticProfile(profile_id=profile_id, **values)
    return profiles


@dataclass(frozen=True)
class SyntheticSettings:
    decision_count: int
    run_count: int
    window: int
    base_seed: int
    temperatures: tuple[float, ...]
    conditions: tuple[str, ...]
    style_weights: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        for name in ("decision_count", "run_count", "window"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} pozitif bir tam sayı olmalı")
        if type(self.base_seed) is not int:
            raise ValueError("base_seed tam sayı olmalı")
        if (not isinstance(self.temperatures, tuple) or not self.temperatures
                or not all(_is_number(t) for t in self.temperatures)):
            raise ValueError("temperatures boş olmayan sayı tuple'ı olmalı")
        known = {w["value"] for w in load_catalog()["weather_conditions"]}
        if (not isinstance(self.conditions, tuple) or not self.conditions
                or not set(self.conditions) <= known):
            raise ValueError("conditions katalogdaki hava kodlarından oluşmalı")
        styles = [row[0] for row in self.style_weights] if isinstance(self.style_weights, tuple) else []
        if (not styles or len(styles) != len(set(styles)) or not set(styles) <= set(load_catalog()["styles"])
                or not all(_is_number(w) and w >= 0 for _, w in self.style_weights)
                or not sum(w for _, w in self.style_weights) > 0):
            raise ValueError("style_weights katalogdaki etkinliklere negatif olmayan ağırlık vermeli")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "SyntheticSettings":
        source = Path(path) if path is not None else _PACKAGE / "synthetic_settings.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {f.name for f in fields(cls)}:
            raise ValueError("Sentetik test ayarlarında eksik veya bilinmeyen alan var")
        if not all(isinstance(data[n], list) for n in ("temperatures", "conditions")):
            raise ValueError("temperatures ve conditions liste olmalı")
        if not isinstance(data["style_weights"], dict):
            raise ValueError("style_weights etkinlik -> ağırlık nesnesi olmalı")
        return cls(**{**data, "temperatures": tuple(data["temperatures"]),
                      "conditions": tuple(data["conditions"]),
                      "style_weights": tuple(data["style_weights"].items())})


def decide(profile: SyntheticProfile, rule_outfit: Outfit, learned_outfit: Outfit,
           rng: random.Random) -> str:
    """Profilin iki kart karşısındaki sonuç kodu; değişiklik ve tepkisizlik üretilmez."""
    rule_utility, learned_utility = profile.utility(rule_outfit), profile.utility(learned_outfit)
    if main_outfit_key(rule_outfit) == main_outfit_key(learned_outfit):
        return "AT" if rule_utility >= profile.accept_threshold else "AR"
    if max(rule_utility, learned_utility) < profile.accept_threshold:
        return "HB"
    if rule_utility == learned_utility:
        return rng.choice(("KT", "OT"))
    return "KT" if rule_utility > learned_utility else "OT"


@dataclass(frozen=True)
class SimulatedDecision:
    index: int
    weather: Weather
    style: str
    candidate_count: int
    result_key: str
    ogrenen_mode: str
    rule_utility: float
    learned_utility: float

    @property
    def selected_method(self) -> str | None:
        """Kabul edilen kart: kural, ogrenen; tek kart gösterildiyse ikisi; aksi hâlde None."""
        _, method, outcome = RESULT_STATUSES[self.result_key]
        if method == "ikisi":
            return method  # AT ve AR: iki yöntem aynı kombini verdi, karşılaştırma yok.
        return method if outcome != "red" else None


def simulate_user(
    profile: SyntheticProfile, wardrobe: Sequence[ClothingItem],
    settings: SyntheticSettings | None = None, *, run_index: int = 0,
    learned_settings: LearnedSettings | None = None,
) -> tuple[SimulatedDecision, ...]:
    """Bir sentetik kullanıcının karşılaştırma dizisi; her gün tek E1 havuzu kurulur."""
    settings = settings if settings is not None else SyntheticSettings.load()
    learned_settings = learned_settings if learned_settings is not None else LearnedSettings.load()
    filter_settings, rule_settings = FilterSettings.load(), RuleSettings.load()
    seed = settings.base_seed + run_index
    rngs = {name: random.Random(f"{seed}:{name}") for name in _RNG_STREAMS}
    user_id = f"sentetik-{profile.profile_id}-{run_index:02d}"
    styles = [style for style, _ in settings.style_weights]
    weights = [weight for _, weight in settings.style_weights]
    history: list[ComparisonDecision] = []
    decisions: list[SimulatedDecision] = []
    attempts = 0
    while len(decisions) < settings.decision_count:
        attempts += 1
        if attempts > 20 * settings.decision_count:
            raise RuntimeError("Sentetik bağlamlarda yeterli aday bulunamadı; dolabı ve ayarları kontrol edin")
        context = rngs["baglam"]
        weather = Weather(context.choice(settings.temperatures), context.choice(settings.conditions))
        style = context.choices(styles, weights)[0]
        pool = generate_candidates(wardrobe, weather, style, settings=filter_settings, rng=rngs["aday"])
        if not pool.candidates:
            continue  # Boş havuzda C# öneri istemez; karar sayılmaz.
        rule = select_rule_outfit(pool.candidates, settings=rule_settings, rng=rngs["kural"])
        learned = select_learned_outfit(pool.candidates, weather, style, history, user_id=user_id,
                                        settings=learned_settings, rng=rngs["ogrenen"])
        assert rule is not None and learned is not None
        key = decide(profile, rule.outfit, learned.outfit, rngs["profil"])
        index = len(decisions) + 1
        history.append(ComparisonDecision(
            user_id=user_id, comparison_id=f"{user_id}-{index:03d}", result_key=key,
            completed_at=_START + timedelta(hours=index), weather=weather, style=style,
            rule_outfit=rule.outfit, learned_outfit=learned.outfit))
        decisions.append(SimulatedDecision(
            index, weather, style, len(pool.candidates), key, learned.ogrenen_mode,
            profile.utility(rule.outfit), profile.utility(learned.outfit)))
    return tuple(decisions)


@dataclass(frozen=True)
class CurvePoint:
    """Bir karşılaştırma sırasındaki, tekrarlar üzerinden ortalama kayan pencere oranları."""

    decision: int
    learned_rate: float
    learned_q1: float
    learned_q3: float
    rule_rate: float
    neither_rate: float
    same_rate: float
    model_rate: float


def _quartiles(values: list[float]) -> tuple[float, float]:
    if len(values) == 1:
        return values[0], values[0]
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return q1, q3


def learning_curve(runs: Sequence[Sequence[SimulatedDecision]], window: int) -> tuple[CurvePoint, ...]:
    """Her sıra için son `window` karşılaştırmadaki seçilme paylarını hesaplar."""
    if not runs or type(window) is not int or window < 1:
        raise ValueError("En az bir tekrar ve pozitif pencere gerekli")
    length = len(runs[0])
    if any(len(run) != length for run in runs):
        raise ValueError("Bütün tekrarlar aynı sayıda karar içermeli")
    points = []
    for i in range(length):
        shares: dict[str, list[float]] = {k: [] for k in ("ogrenen", "kural", "none", "ikisi", "model")}
        for run in runs:
            span = run[max(0, i + 1 - window): i + 1]
            for name in ("ogrenen", "kural", "ikisi"):
                shares[name].append(sum(d.selected_method == name for d in span) / len(span))
            shares["none"].append(sum(d.selected_method is None for d in span) / len(span))
            shares["model"].append(sum(d.ogrenen_mode == "model" for d in span) / len(span))
        q1, q3 = _quartiles(shares["ogrenen"])
        points.append(CurvePoint(i + 1, statistics.fmean(shares["ogrenen"]), q1, q3,
                                 statistics.fmean(shares["kural"]), statistics.fmean(shares["none"]),
                                 statistics.fmean(shares["ikisi"]), statistics.fmean(shares["model"])))
    return tuple(points)


def crossover_point(curve: Sequence[CurvePoint]) -> int | None:
    """Öğrenen kartın sonuna kadar kural kartından sık seçildiği ilk karşılaştırma."""
    for k, point in enumerate(curve):
        if all(p.learned_rate > p.rule_rate for p in curve[k:]):
            return point.decision
    return None


def first_model_decision(runs: Sequence[Sequence[SimulatedDecision]]) -> float | None:
    """Soğuk başlangıç bitip öğrenen kartın ilk kez model/keşifle seçildiği sıranın medyanı."""
    firsts = [next((d.index for d in run if d.ogrenen_mode != "soguk_baslangic"), None) for run in runs]
    firsts = [f for f in firsts if f is not None]
    return statistics.median(firsts) if firsts else None


def write_curve_csv(curve: Sequence[CurvePoint], path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("karsilastirma", "ogrenen_orani", "ogrenen_q1", "ogrenen_q3", "kural_orani",
                         "ikisi_de_secilmedi_orani", "tek_kart_orani", "model_modu_orani"))
        for p in curve:
            writer.writerow((p.decision, *(f"{v:.4f}" for v in (
                p.learned_rate, p.learned_q1, p.learned_q3, p.rule_rate,
                p.neither_rate, p.same_rate, p.model_rate))))


# Doğrulanmış iki renk (dataviz varsayılan paleti 1. ve 2. yuva) ve grafik mürekkepleri.
_LEARNED_COLOR, _RULE_COLOR = "#2a78d6", "#eb6834"
_INK, _INK_SECONDARY, _MUTED = "#0b0b0b", "#52514e", "#898781"
_GRID, _AXIS, _SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"


def plot_learning_curve(
    curve: Sequence[CurvePoint], profile: SyntheticProfile, path: str | Path, *,
    run_count: int, window: int, crossover: int | None, cold_start_end: float | None,
) -> None:
    """Tek grafik: kayan pencerede öğrenen ve kural kartlarının seçilme oranı."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from matplotlib.ticker import PercentFormatter

    x = [p.decision for p in curve]
    learned = [100 * p.learned_rate for p in curve]
    rule = [100 * p.rule_rate for p in curve]
    fig = Figure(figsize=(9, 5.2), facecolor=_SURFACE)
    ax = fig.add_axes((0.08, 0.17, 0.78, 0.66), facecolor=_SURFACE)
    ax.fill_between(x, [100 * p.learned_q1 for p in curve], [100 * p.learned_q3 for p in curve],
                    color=_LEARNED_COLOR, alpha=0.14, linewidth=0, label="Öğrenen · tekrarlar arası çeyrek aralığı")
    ax.plot(x, learned, color=_LEARNED_COLOR, linewidth=2, label="Öğrenen kart seçildi")
    ax.plot(x, rule, color=_RULE_COLOR, linewidth=2, linestyle=(0, (5, 2)), label="Kural kartı seçildi")
    for values, color, text in ((learned, _LEARNED_COLOR, "Öğrenen"), (rule, _RULE_COLOR, "Kural")):
        ax.plot(x[-1], values[-1], "o", color=color, markersize=6, markeredgecolor=_SURFACE, markeredgewidth=2)
        ax.annotate(f"{text} %{values[-1]:.0f}", (x[-1], values[-1]), xytext=(8, 0),
                    textcoords="offset points", va="center", fontsize=10, color=_INK)
    if cold_start_end is not None:
        ax.axvline(cold_start_end, color=_MUTED, linewidth=1, linestyle=":")
        ax.annotate(f"soğuk başlangıç biter\n(medyan {cold_start_end:g}. karşılaştırma)", (cold_start_end, 97),
                    xytext=(-6, 0), textcoords="offset points", ha="right", va="top", fontsize=9, color=_INK_SECONDARY)
    if crossover is not None:
        ax.axvline(crossover, color=_INK_SECONDARY, linewidth=1, linestyle="--")
        ax.annotate(f"kesişme: {crossover}. karşılaştırma\nsonrasında öğrenen hep önde", (crossover, 97),
                    xytext=(6, 0), textcoords="offset points", ha="left", va="top", fontsize=9, color=_INK_SECONDARY)
    ax.set_xlim(1, x[-1])
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_xlabel("Karşılaştırma sırası", color=_INK_SECONDARY)
    ax.set_ylabel(f"Son {window} karşılaştırmada seçilme payı", color=_INK_SECONDARY)
    ax.grid(axis="y", color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(_AXIS)
    ax.tick_params(colors=_MUTED, length=0)
    ax.legend(loc="center right", bbox_to_anchor=(1.0, 0.42), frameon=False, fontsize=9, labelcolor=_INK_SECONDARY)
    fig.text(0.08, 0.93, "Öğrenen kart kaç karşılaştırmadan sonra daha sık seçiliyor?",
             fontsize=14, fontweight="bold", color=_INK)
    fig.text(0.08, 0.88, f"SENTETİK profil «{profile.profile_id}»: {profile.description} · "
             f"{run_count} tekrar ortalaması", fontsize=10, color=_INK_SECONDARY)
    fig.text(0.08, 0.04, "Sentetik kullanıcı testidir; gerçek kullanıcı verisi değildir. "
             "Kalan pay: ikisi de seçilmedi ya da iki kart aynı.", fontsize=8.5, color=_MUTED)
    fig.savefig(path, dpi=150, facecolor=_SURFACE)


def main() -> None:
    parser = argparse.ArgumentParser(description="E10 sentetik kullanıcı testi ve öğrenme grafiği")
    parser.add_argument("--profile", default="notr_koyu")
    parser.add_argument("--runs", type=int, help="Tekrar sayısı; verilmezse ayar dosyası")
    parser.add_argument("--decisions", type=int, help="Karşılaştırma sayısı; verilmezse ayar dosyası")
    parser.add_argument("--output-dir", type=Path, default=_PACKAGE.parent / "docs" / "figures")
    parser.add_argument("--wardrobe", type=Path, default=_PACKAGE.parent / "tests" / "sample_wardrobe.json")
    parser.add_argument("--no-plot", action="store_true", help="Yalnız özet ve CSV")
    args = parser.parse_args()
    profiles = load_profiles()
    if args.profile not in profiles:
        parser.error(f"Bilinmeyen profil: {args.profile} (seçenekler: {', '.join(profiles)})")
    profile = profiles[args.profile]
    base = SyntheticSettings.load()
    settings = SyntheticSettings(**{**{f.name: getattr(base, f.name) for f in fields(base)},
                                    "run_count": base.run_count if args.runs is None else args.runs,
                                    "decision_count": (base.decision_count if args.decisions is None
                                                       else args.decisions)})
    wardrobe = load_wardrobe(args.wardrobe)
    runs = [simulate_user(profile, wardrobe, settings, run_index=i) for i in range(settings.run_count)]
    curve = learning_curve(runs, settings.window)
    crossover, cold_end = crossover_point(curve), first_model_decision(runs)
    keys = [d.result_key for run in runs for d in run]
    print("SENTETİK TEST: sonuçlar gerçek kullanıcı verisi değildir.")
    print(f"Profil: {profile.profile_id} ({profile.description})")
    print(f"Tekrar: {settings.run_count} | Karşılaştırma: {settings.decision_count} | Pencere: {settings.window}")
    print("Sonuç kodları: " + ", ".join(f"{k}={keys.count(k)}" for k in sorted(set(keys))))
    print(f"Soğuk başlangıcın bittiği sıra (medyan): {cold_end}")
    print(f"Kesişme: {crossover if crossover is not None else 'yok'}")
    last = curve[-1]
    print(f"Son pencere: öğrenen %{100 * last.learned_rate:.0f} | kural %{100 * last.rule_rate:.0f} | "
          f"ikisi de seçilmedi %{100 * last.neither_rate:.0f} | tek kart %{100 * last.same_rate:.0f}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.output_dir / f"E10-{profile.profile_id}"
    write_curve_csv(curve, stem.with_suffix(".csv"))
    print(f"CSV: {stem.with_suffix('.csv')}")
    if not args.no_plot:
        plot_learning_curve(curve, profile, stem.with_suffix(".png"), run_count=settings.run_count,
                            window=settings.window, crossover=crossover, cold_start_end=cold_end)
        print(f"Grafik: {stem.with_suffix('.png')}")


if __name__ == "__main__":
    main()

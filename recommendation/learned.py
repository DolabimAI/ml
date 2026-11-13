"""E4: her çağrıda yalnız kullanıcının geçmişinden öğrenen kart seçimi."""

import json
import math
import random
import warnings
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterable

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .features import encode_outfits, feature_names
from .filter import Outfit
from .history import ComparisonDecision, build_training_data
from .models import Weather


@dataclass(frozen=True)
class LearnedSettings:
    cold_start_limit: int = 10
    rule_learning_limit: int = 10
    exploration_rate: float = 0.10
    solver: str = "lbfgs"
    l1_ratio: float = 0.0
    C: float = 1.0
    tol: float = 1e-4
    max_iter: int = 1000
    class_weight: None = None
    warm_start: bool = False

    def __post_init__(self) -> None:
        for name in ("cold_start_limit", "rule_learning_limit", "max_iter"):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if name == "max_iter" else 0):
                raise ValueError(f"Geçersiz {name}")
        for name in ("exploration_rate", "C", "tol", "l1_ratio"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} sonlu bir sayı olmalı")
        if not 0 <= self.exploration_rate <= 1 or self.C <= 0 or self.tol <= 0:
            raise ValueError("Keşif oranı [0, 1], C ve tol pozitif olmalı")
        if (self.solver != "lbfgs" or self.l1_ratio != 0 or self.class_weight is not None
                or self.warm_start is not False):
            raise ValueError("Bu sürüm lbfgs/L2, class_weight=None ve warm_start=False kullanır")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "LearnedSettings":
        source = Path(path) if path is not None else Path(__file__).with_name("learned_settings.json")
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {f.name for f in fields(cls)}:
            raise ValueError("Öğrenen ayarlarında eksik veya bilinmeyen alan var")
        return cls(**data)


@dataclass(frozen=True)
class LearnedSelection:
    outfit: Outfit
    ogrenen_mode: str
    probability: float | None
    reason: str | None
    decision_count: int
    rule_decision_count: int
    positive_count: int
    negative_count: int


def _make_pipeline(settings: LearnedSettings) -> Pipeline:
    names = feature_names()
    numeric = [names.index("context.feels_like_temp"), names.index("outfit.vivid_color_count")]
    return Pipeline([
        ("preprocess", ColumnTransformer([("numeric", StandardScaler(), numeric)],
                                         remainder="passthrough", sparse_threshold=0)),
        ("classifier", LogisticRegression(solver=settings.solver, l1_ratio=settings.l1_ratio,
                                          C=settings.C, tol=settings.tol, max_iter=settings.max_iter,
                                          class_weight=settings.class_weight, warm_start=settings.warm_start)),
    ])


def select_learned_outfit(
    candidates: Iterable[Outfit], weather: Weather, style: str, history: Iterable[ComparisonDecision],
    *, user_id: str, settings: LearnedSettings | None = None, rng: random.Random | None = None,
) -> LearnedSelection | None:
    """E1 havuzunu değiştirmez. Model ve ölçekleyici yalnız bu çağrıda yaşar."""
    candidates = tuple(candidates)
    if not candidates:
        return None
    settings = settings if settings is not None else LearnedSettings.load()
    rng = rng if rng is not None else random.Random()
    # Hatalı adayları rastgele dallarda da sessizce kabul etme.
    candidate_vectors = encode_outfits(candidates, weather, style)
    data = build_training_data(history, user_id=user_id, rule_learning_limit=settings.rule_learning_limit)

    def selection(outfit: Outfit, mode: str, probability: float | None = None,
                  reason: str | None = None) -> LearnedSelection:
        return LearnedSelection(outfit, mode, probability, reason, data.decision_count,
                                data.rule_decision_count, data.positive_count, data.negative_count)

    reason = None
    if data.decision_count < settings.cold_start_limit:
        reason = "yetersiz_karar"
    elif not data.examples:
        reason = "ornek_yok"
    elif not data.positive_count or not data.negative_count:
        reason = "tek_sinif"
    if reason is not None:
        return selection(rng.choice(candidates), "soguk_baslangic", reason=reason)

    model = _make_pipeline(settings)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        try:
            model.fit([e.features for e in data.examples], [e.label for e in data.examples])
        except ConvergenceWarning as exc:
            raise RuntimeError("Öğrenen model yakınsamadı; ayarları ve eğitim verisini kontrol edin") from exc
    # Keşif yapılacak olsa da uygun her çağrıda güncel geçmişle yeniden eğitim yapılır.
    if rng.random() < settings.exploration_rate:
        return selection(rng.choice(candidates), "kesif")
    positive_column = list(model.classes_).index(1)
    probabilities = model.predict_proba(candidate_vectors)[:, positive_column]
    if not np.all(np.isfinite(probabilities)) or np.any((probabilities < 0) | (probabilities > 1)):
        raise RuntimeError("Model geçersiz olasılık üretti")
    highest = float(max(probabilities))
    best = [outfit for outfit, p in zip(candidates, probabilities, strict=True) if p == highest]
    return selection(rng.choice(best), "model", highest)

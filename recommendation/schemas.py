"""E7: A3 sözleşmesindeki /recommend istek biçimi (camelCase) ve iç modellere çevrimi.

JSON alanları camelCase gelir; iç kod snake_case kalır. Modeller sıkıdır: bilinmeyen alan,
yanlış tür ("true" metni, "1" metni) ve bilinmeyen kod `invalid_request` olarak reddedilir.
Kodların doğrulaması mevcut iç modellere (`ClothingItem`, `Weather`, `ComparisonDecision`)
bırakılır; kod listesi burada yeniden yazılmaz.
"""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

from .filter import Outfit
from .history import LEARNING_KEYS, ComparisonDecision
from .models import ClothingItem, Weather, load_catalog


class ContractModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid",
                              strict=True, frozen=True)


class ItemIn(ContractModel):
    id: int
    subtype: str
    category: str
    color: str
    tone: str
    is_patterned: bool
    styles: list[str]
    min_temp: float
    max_temp: float
    avoid_when_wet: bool
    preferred_when_wet: bool
    preferred_when_hot: bool
    status: str

    def to_domain(self) -> ClothingItem:
        return ClothingItem(**{**self.model_dump(), "styles": tuple(self.styles)})


class OutfitIn(ContractModel):
    template: Literal["ust_alt", "tek_parca"]
    items: list[ItemIn]

    def to_domain(self) -> Outfit:
        return Outfit(self.template, tuple(item.to_domain() for item in self.items))


class ContextIn(ContractModel):
    feels_like_temp: float
    weather_condition: str
    time_of_day: Literal["sabah", "ogle", "aksam", "gece"]
    is_daytime: bool
    event_style: str
    wants_accessories: bool


class HistoryContextIn(ContractModel):
    feels_like_temp: float
    weather_condition: str
    event_style: str


class HistoryIn(ContractModel):
    comparison_id: int
    result_key: str
    completed_at: AwareDatetime
    context: HistoryContextIn
    rule_outfit: OutfitIn
    learned_outfit: OutfitIn
    final_outfit: OutfitIn | None = None

    @field_validator("result_key")
    @classmethod
    def _learning_key_only(cls, value: str) -> str:
        if value not in LEARNING_KEYS:
            raise ValueError(f"Geçmişte yalnız {', '.join(sorted(LEARNING_KEYS))} kabul edilir")
        return value

    def to_domain(self, user_id: str) -> ComparisonDecision:
        return ComparisonDecision(
            user_id=user_id, comparison_id=str(self.comparison_id), result_key=self.result_key,
            completed_at=self.completed_at,
            weather=Weather(self.context.feels_like_temp, self.context.weather_condition),
            style=self.context.event_style,
            rule_outfit=self.rule_outfit.to_domain(), learned_outfit=self.learned_outfit.to_domain(),
            final_outfit=self.final_outfit.to_domain() if self.final_outfit is not None else None,
        )


class RecommendRequest(ContractModel):
    user_id: UUID
    context: ContextIn
    wardrobe: list[ItemIn]
    rejected_outfits: list[list[int]]
    history: list[HistoryIn]

    def to_domain(self) -> dict:
        """`recommend()` için anahtar kelime argümanları (rng hariç).

        Biçim dışındaki tutarlılık hataları da burada yakalanır; böylece hesaplama
        sırasında çıkan her hata gerçekten beklenmeyen (`internal_error`) bir hatadır.
        """
        context = self.context
        if context.event_style not in load_catalog()["styles"]:
            raise ValueError(f"Bilinmeyen etkinlik: {context.event_style}")
        wardrobe = tuple(item.to_domain() for item in self.wardrobe)
        if len({item.id for item in wardrobe}) != len(wardrobe):
            raise ValueError("wardrobe aynı parça id'sini birden fazla kez içeremez")
        for ids in self.rejected_outfits:
            if not ids or any(i < 1 for i in ids) or len(ids) != len(set(ids)):
                raise ValueError("rejectedOutfits her biri benzersiz pozitif id'lerden oluşan "
                                 "boş olmayan listeler içermeli")
        comparison_ids = [entry.comparison_id for entry in self.history]
        if len(comparison_ids) != len(set(comparison_ids)):
            raise ValueError("history aynı comparisonId'yi birden fazla kez içeremez")
        user_id = str(self.user_id)
        return {
            "wardrobe": wardrobe,
            "weather": Weather(context.feels_like_temp, context.weather_condition),
            "style": context.event_style,
            "is_daytime": context.is_daytime,
            "wants_accessories": context.wants_accessories,
            "rejected_outfits": tuple(tuple(ids) for ids in self.rejected_outfits),
            "history": tuple(entry.to_domain(user_id) for entry in self.history),
            "user_id": user_id,
        }

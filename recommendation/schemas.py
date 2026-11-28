"""E7, E5: A3 sözleşmesindeki /recommend ve /swap istek biçimleri (camelCase) ve iç modellere çevrimi.

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


def _validated_wardrobe(context: ContextIn, items: list[ItemIn]) -> tuple[ClothingItem, ...]:
    if context.event_style not in load_catalog()["styles"]:
        raise ValueError(f"Bilinmeyen etkinlik: {context.event_style}")
    wardrobe = tuple(item.to_domain() for item in items)
    if len({item.id for item in wardrobe}) != len(wardrobe):
        raise ValueError("wardrobe aynı parça id'sini birden fazla kez içeremez")
    return wardrobe


def _validated_history(entries: list[HistoryIn], user_id: str) -> tuple[ComparisonDecision, ...]:
    comparison_ids = [entry.comparison_id for entry in entries]
    if len(comparison_ids) != len(set(comparison_ids)):
        raise ValueError("history aynı comparisonId'yi birden fazla kez içeremez")
    return tuple(entry.to_domain(user_id) for entry in entries)


def _context_kwargs(context: ContextIn, wardrobe: tuple[ClothingItem, ...]) -> dict:
    return {
        "wardrobe": wardrobe,
        "weather": Weather(context.feels_like_temp, context.weather_condition),
        "style": context.event_style,
        "is_daytime": context.is_daytime,
        "wants_accessories": context.wants_accessories,
    }


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
        wardrobe = _validated_wardrobe(context, self.wardrobe)
        for ids in self.rejected_outfits:
            if not ids or any(i < 1 for i in ids) or len(ids) != len(set(ids)):
                raise ValueError("rejectedOutfits her biri benzersiz pozitif id'lerden oluşan "
                                 "boş olmayan listeler içermeli")
        user_id = str(self.user_id)
        return {
            **_context_kwargs(context, wardrobe),
            "rejected_outfits": tuple(tuple(ids) for ids in self.rejected_outfits),
            "history": _validated_history(self.history, user_id),
            "user_id": user_id,
        }


TEMPLATE_CATEGORIES = {
    "ust_alt": ({"ust", "alt", "ayakkabi"}, {"dis"}),
    "tek_parca": ({"tek_parca", "ayakkabi"}, {"dis"}),
}


class CurrentOutfitIn(ContractModel):
    template: Literal["ust_alt", "tek_parca"]
    item_ids: list[int]
    accessory_ids: list[int]


class SwapRequest(ContractModel):
    user_id: UUID
    method: Literal["kural", "ogrenen", "ortak_kural"]
    context: ContextIn
    current_outfit: CurrentOutfitIn
    target_category: str | None = None
    target_accessory_id: int | None = None
    excluded_item_ids: list[int]
    wardrobe: list[ItemIn]
    history: list[HistoryIn]

    def to_domain(self) -> dict:
        """`swap()` için anahtar kelime argümanları (rng hariç).

        Kombin, hedef ve yöntem tutarlılığı burada denetlenir; hesaplama sırasında çıkan
        her hata gerçekten beklenmeyen (`internal_error`) bir hatadır.
        """
        wardrobe = _validated_wardrobe(self.context, self.wardrobe)
        by_id = {item.id: item for item in wardrobe}
        current = self.current_outfit

        ids = current.item_ids + current.accessory_ids
        if len(ids) != len(set(ids)):
            raise ValueError("currentOutfit aynı parçayı birden fazla kez içeremez")
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise ValueError(f"currentOutfit parçaları wardrobe'da yok: {missing}")
        items = tuple(by_id[i] for i in current.item_ids)
        accessories = tuple(by_id[i] for i in current.accessory_ids)
        categories = [item.category for item in items]
        required, optional = TEMPLATE_CATEGORIES[current.template]
        if len(categories) != len(set(categories)) or not required <= set(categories) <= required | optional:
            raise ValueError(f"currentOutfit.itemIds {current.template} şablonuna uymuyor")
        if any(item.category != "aksesuar" for item in accessories):
            raise ValueError("currentOutfit.accessoryIds yalnız aksesuar içerebilir")

        if self.method == "ortak_kural":
            if self.target_category is not None or self.target_accessory_id is None:
                raise ValueError("ortak_kural yalnız targetAccessoryId ile kullanılır")
            if self.target_accessory_id not in current.accessory_ids:
                raise ValueError("targetAccessoryId kombindeki aksesuarlardan biri olmalı")
        else:
            if self.target_category is None or self.target_accessory_id is not None:
                raise ValueError(f"{self.method} yalnız targetCategory ile kullanılır")
            if self.target_category not in categories:
                raise ValueError("targetCategory kombindeki ana parçalardan birinin kategorisi olmalı")

        if any(i < 1 for i in self.excluded_item_ids):
            raise ValueError("excludedItemIds pozitif id'lerden oluşmalı")
        if self.history and self.method != "ogrenen":
            raise ValueError("history yalnız ogrenen yönteminde dolu olabilir")

        user_id = str(self.user_id)
        return {
            **_context_kwargs(self.context, wardrobe),
            "method": self.method,
            "outfit": Outfit(current.template, items),
            "accessories": accessories,
            "target_category": self.target_category,
            "target_accessory_id": self.target_accessory_id,
            "excluded_item_ids": frozenset(self.excluded_item_ids),
            "history": _validated_history(self.history, user_id),
            "user_id": user_id,
        }

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Offer:
    store: str  # "mercadolivre" | "shopee" | "amazon"
    external_id: str
    title: str
    price: float
    old_price: Optional[float]
    url: str
    image_url: Optional[str] = None
    category: str = ""

    @property
    def discount_pct(self) -> int:
        if self.old_price and self.old_price > self.price > 0:
            return round(((self.old_price - self.price) / self.old_price) * 100)
        return 0

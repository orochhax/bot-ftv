import unicodedata

from src.config import CategoryRule, RulesConfig
from src.models import Offer


def normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _matches_keyword(norm_title: str, keyword: str) -> bool:
    tokens = [t for t in normalize_text(keyword).split() if len(t) > 1]
    return bool(tokens) and all(token in norm_title for token in tokens)


def match_category(title: str, categories: list[CategoryRule]) -> CategoryRule | None:
    norm_title = normalize_text(title)
    for cat in categories:
        if any(_matches_keyword(norm_title, kw) for kw in cat.keywords):
            return cat
    return None


def is_blacklisted(title: str, blacklist: list[str]) -> bool:
    norm_title = normalize_text(title)
    return any(normalize_text(term) in norm_title for term in blacklist)


def filter_offers(offers: list[Offer], rules: RulesConfig) -> list[Offer]:
    approved: list[Offer] = []
    seen_keys: set[tuple[str, str]] = set()

    for offer in offers:
        key = (offer.store, offer.external_id)
        if key in seen_keys or offer.price <= 0:
            continue
        if is_blacklisted(offer.title, rules.global_blacklist):
            continue

        category = match_category(offer.title, rules.categories)
        if category is None:
            continue

        if not (category.min_price <= offer.price <= category.max_price):
            continue

        has_real_discount = offer.discount_pct >= rules.min_discount_pct
        below_promo_ceiling = offer.price <= category.promo_ceiling
        if not (has_real_discount or below_promo_ceiling):
            continue

        seen_keys.add(key)
        approved.append(
            Offer(
                store=offer.store,
                external_id=offer.external_id,
                title=offer.title.strip(),
                price=offer.price,
                old_price=offer.old_price,
                url=offer.url,
                image_url=offer.image_url,
                category=category.name,
            )
        )

    approved.sort(key=lambda o: (o.discount_pct, -o.price), reverse=True)
    return approved

import logging
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from src.models import Offer

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.mercadolibre.com/sites/MLB/search"


def _attach_affiliate_param(url: str, affiliate_param: str) -> str:
    if not affiliate_param:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    for k, v in parse_qsl(affiliate_param.lstrip("?&")):
        query[k] = v
    return urlunparse(parsed._replace(query=urlencode(query)))


class MercadoLivreCollector:
    name = "mercadolivre"

    def __init__(self, access_token: str = "", affiliate_param: str = "") -> None:
        self.access_token = access_token
        self.affiliate_param = affiliate_param

    def fetch(self, keywords: list[str], limit_per_keyword: int = 20) -> list[Offer]:
        headers = {"User-Agent": "bot-ftv/1.0"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        offers: list[Offer] = []
        with httpx.Client(timeout=20.0, headers=headers) as client:
            for kw in keywords:
                resp = client.get(
                    SEARCH_URL,
                    params={"q": kw, "limit": limit_per_keyword, "condition": "new"},
                )
                resp.raise_for_status()
                for item in resp.json().get("results", []):
                    price = float(item.get("price") or 0)
                    raw_old = item.get("original_price")
                    old_price = float(raw_old) if raw_old else None
                    permalink = item.get("permalink") or ""
                    item_id = str(item.get("id") or "")
                    if not item_id or not permalink or price <= 0:
                        continue

                    thumb = item.get("thumbnail") or ""
                    if thumb.startswith("http://"):
                        thumb = "https://" + thumb[len("http://") :]
                    image_url = thumb.replace("-I.jpg", "-O.jpg") if thumb else None

                    offers.append(
                        Offer(
                            store=self.name,
                            external_id=item_id,
                            title=str(item.get("title") or ""),
                            price=price,
                            old_price=old_price,
                            url=_attach_affiliate_param(permalink, self.affiliate_param),
                            image_url=image_url,
                        )
                    )
        logger.info("Mercado Livre retornou %d itens brutos", len(offers))
        return offers

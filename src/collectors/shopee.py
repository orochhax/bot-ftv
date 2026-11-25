import hashlib
import json
import logging
import time

import httpx

from src.models import Offer

logger = logging.getLogger(__name__)

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"

QUERY = """
query ProductOffer($keyword: String!, $limit: Int!) {
  productOfferV2(keyword: $keyword, listType: 0, sortType: 2, limit: $limit) {
    nodes {
      itemId
      productName
      priceMin
      priceDiscountRate
      offerLink
      imageUrl
    }
  }
}
"""


def build_shopee_auth_header(app_id: str, app_secret: str, payload: str, timestamp: int) -> str:
    raw = f"{app_id}{timestamp}{payload}{app_secret}"
    signature = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"


class ShopeeCollector:
    name = "shopee"

    def __init__(self, app_id: str, app_secret: str) -> None:
        self.app_id = app_id
        self.app_secret = app_secret

    def fetch(self, keywords: list[str], limit_per_keyword: int = 20) -> list[Offer]:
        if not self.app_id or not self.app_secret:
            raise ValueError("SHOPEE_APP_ID e SHOPEE_APP_SECRET sao obrigatorios quando ENABLE_SHOPEE=true")

        offers: list[Offer] = []
        with httpx.Client(timeout=20.0) as client:
            for kw in keywords:
                body = json.dumps(
                    {"query": QUERY, "variables": {"keyword": kw, "limit": limit_per_keyword}},
                    separators=(",", ":"),
                )
                ts = int(time.time())
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": build_shopee_auth_header(self.app_id, self.app_secret, body, ts),
                }
                resp = client.post(ENDPOINT, content=body.encode("utf-8"), headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if data.get("errors"):
                    raise RuntimeError(f"Shopee GraphQL error: {data['errors']}")

                nodes = data.get("data", {}).get("productOfferV2", {}).get("nodes", [])
                for node in nodes:
                    price = float(node.get("priceMin") or 0)
                    rate = int(node.get("priceDiscountRate") or 0)
                    old_price = round(price / (1 - rate / 100), 2) if 0 < rate < 95 and price > 0 else None
                    item_id = str(node.get("itemId") or "")
                    link = str(node.get("offerLink") or "")
                    if not item_id or not link or price <= 0:
                        continue

                    offers.append(
                        Offer(
                            store=self.name,
                            external_id=item_id,
                            title=str(node.get("productName") or ""),
                            price=price,
                            old_price=old_price,
                            url=link,
                            image_url=node.get("imageUrl") or None,
                        )
                    )
        logger.info("Shopee retornou %d itens brutos", len(offers))
        return offers

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging

import httpx

from src.models import Offer

logger = logging.getLogger(__name__)

HOST = "webservices.amazon.com.br"
REGION = "us-east-1"
SERVICE = "ProductAdvertisingAPI"
PATH = "/paapi5/searchitems"
TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _build_sigv4_headers(access_key: str, secret_key: str, payload: str, now: datetime) -> dict[str, str]:
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    content_type = "application/json; charset=utf-8"

    canonical_headers = (
        f"content-encoding:amz-1.0\n"
        f"content-type:{content_type}\n"
        f"host:{HOST}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{TARGET}\n"
    )
    signed_headers = "content-encoding;content-type;host;x-amz-date;x-amz-target"
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = f"POST\n{PATH}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

    credential_scope = f"{date_stamp}/{REGION}/{SERVICE}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, REGION)
    k_service = _sign(k_region, SERVICE)
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        "Content-Encoding": "amz-1.0",
        "Content-Type": content_type,
        "Host": HOST,
        "X-Amz-Date": amz_date,
        "X-Amz-Target": TARGET,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }


class AmazonCollector:
    name = "amazon"

    def __init__(self, access_key: str, secret_key: str, partner_tag: str) -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.partner_tag = partner_tag

    def fetch(self, keywords: list[str], limit_per_keyword: int = 10) -> list[Offer]:
        if not (self.access_key and self.secret_key and self.partner_tag):
            raise ValueError("Credenciais AMAZON_* sao obrigatorias quando ENABLE_AMAZON=true")

        offers: list[Offer] = []
        with httpx.Client(timeout=20.0) as client:
            for kw in keywords:
                payload = json.dumps(
                    {
                        "Keywords": kw,
                        "PartnerTag": self.partner_tag,
                        "PartnerType": "Associates",
                        "Marketplace": "www.amazon.com.br",
                        "ItemCount": min(limit_per_keyword, 10),
                        "Resources": [
                            "Images.Primary.Large",
                            "ItemInfo.Title",
                            "Offers.Listings.Price",
                            "Offers.Listings.SavingBasis",
                        ],
                    },
                    separators=(",", ":"),
                )
                headers = _build_sigv4_headers(
                    self.access_key,
                    self.secret_key,
                    payload,
                    datetime.now(timezone.utc),
                )
                resp = client.post(f"https://{HOST}{PATH}", content=payload.encode("utf-8"), headers=headers)
                resp.raise_for_status()
                items = resp.json().get("SearchResult", {}).get("Items", [])
                for item in items:
                    asin = str(item.get("ASIN") or "")
                    url = str(item.get("DetailPageURL") or "")
                    title = str(item.get("ItemInfo", {}).get("Title", {}).get("DisplayValue") or "")
                    listings = item.get("Offers", {}).get("Listings", [])
                    if not (asin and url and title and listings):
                        continue

                    listing = listings[0]
                    price = float(listing.get("Price", {}).get("Amount") or 0)
                    saving_basis = listing.get("SavingBasis", {}).get("Amount")
                    old_price = float(saving_basis) if saving_basis else None
                    image_url = item.get("Images", {}).get("Primary", {}).get("Large", {}).get("URL")
                    if price <= 0:
                        continue

                    offers.append(
                        Offer(
                            store=self.name,
                            external_id=asin,
                            title=title,
                            price=price,
                            old_price=old_price,
                            url=url,
                            image_url=image_url,
                        )
                    )
        logger.info("Amazon retornou %d itens brutos", len(offers))
        return offers

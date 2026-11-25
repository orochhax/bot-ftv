import html
import logging

import httpx

from src.models import Offer

logger = logging.getLogger(__name__)

STORE_LABELS = {
    "mercadolivre": "Mercado Livre",
    "shopee": "Shopee",
    "amazon": "Amazon",
}


def format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_offer_html(offer: Offer, variant_index: int = 0, channel_invite_url: str = "") -> str:
    title = html.escape(offer.title[:160])
    store_name = STORE_LABELS.get(offer.store, offer.store.title())
    safe_url = html.escape(offer.url, quote=True)

    lines = [
        f"🔥 <b>{title}</b>",
        "",
        f"- {html.escape(store_name)}",
        "",
    ]
    if offer.old_price and offer.old_price > offer.price and offer.discount_pct > 0:
        lines.append(
            f"💰 De <s>{format_brl(offer.old_price)}</s> por <b>{format_brl(offer.price)}</b> "
            f"(<b>-{offer.discount_pct}% OFF</b>)"
        )
    else:
        lines.append(f"💰 <b>{format_brl(offer.price)}</b>")

    lines.extend(
        [
            "",
            "🔗 Link do produto:",
            safe_url,
        ]
    )

    if channel_invite_url:
        safe_invite = html.escape(channel_invite_url.strip(), quote=True)
        lines.extend(
            [
                "",
                "👉 Compartilhe com os amigos:",
                safe_invite,
            ]
        )

    return "\n".join(lines)


class TelegramPublisher:
    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        admin_chat_id: str = "",
        channel_invite_url: str = "",
    ) -> None:
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.admin_chat_id = admin_chat_id
        self.channel_invite_url = channel_invite_url
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def _post(self, method: str, payload: dict) -> dict:
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(f"{self.base_url}/{method}", json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Telegram API error: {data}")
            return data

    def send_offer(self, offer: Offer, variant_index: int = 0) -> None:
        caption = format_offer_html(
            offer,
            variant_index=variant_index,
            channel_invite_url=self.channel_invite_url,
        )
        if offer.image_url:
            try:
                self._post(
                    "sendPhoto",
                    {
                        "chat_id": self.channel_id,
                        "photo": offer.image_url,
                        "caption": caption,
                        "parse_mode": "HTML",
                    },
                )
                return
            except Exception as exc:
                logger.warning("sendPhoto falhou (%s); fazendo fallback para sendMessage", exc)

        self._post(
            "sendMessage",
            {
                "chat_id": self.channel_id,
                "text": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )

    def notify_admin(self, text: str) -> None:
        if not self.bot_token or not self.admin_chat_id:
            return
        try:
            self._post(
                "sendMessage",
                {
                    "chat_id": self.admin_chat_id,
                    "text": text[:3800],
                    "parse_mode": "HTML",
                },
            )
        except Exception as exc:
            logger.error("Falha ao notificar admin no Telegram: %s", exc)

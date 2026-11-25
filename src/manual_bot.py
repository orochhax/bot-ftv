import html as html_lib
import logging
import re
import time
from urllib.parse import urlparse

import httpx

from src.config import Settings
from src.db import Database
from src.models import Offer
from src.telegram import TelegramPublisher

logger = logging.getLogger("bot-ftv.manual")

URL_RE = re.compile(r"https?://\S+")


def infer_store(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "mercadoli" in host or "meli." in host:
        return "mercadolivre"
    if "shopee" in host or "shope." in host or "s.shopee" in host:
        return "shopee"
    if "amazon" in host or "amzn." in host:
        return "amazon"
    return "oferta"


def parse_price(raw: str) -> float:
    cleaned = re.sub(r"[^\d,\.]", "", raw.strip())
    if not cleaned:
        raise ValueError("preco vazio")
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    val = float(cleaned)
    if val <= 0:
        raise ValueError("preco invalido")
    return val


def parse_postar_command(text: str, photo_file_id: str | None = None) -> Offer:
    """Aceita:
    /postar Titulo | preco | preco_antigo | url
    /postar Titulo | preco | url
    """
    body = re.sub(r"^/postar(?:@\w+)?\s*", "", text.strip(), flags=re.IGNORECASE)
    parts = [p.strip() for p in body.split("|") if p.strip()]
    if len(parts) not in {3, 4}:
        raise ValueError(
            "Formato invalido. Use:\n"
            "/postar Titulo | preco | url\n"
            "ou\n"
            "/postar Titulo | preco | preco_antigo | url"
        )

    title = parts[0]
    price = parse_price(parts[1])
    if len(parts) == 3:
        old_price = None
        url = parts[2]
    else:
        old_price = parse_price(parts[2])
        url = parts[3]

    if not url.startswith(("http://", "https://")):
        raise ValueError("A ultima parte precisa ser um link valido (https://...).")

    return Offer(
        store=infer_store(url),
        external_id=f"manual-{abs(hash(url)) % 10**10}",
        title=title,
        price=price,
        old_price=old_price,
        url=url,
        image_url=photo_file_id,
        category="Manual",
    )


def _extract_meta(page_html: str, prop: str) -> str:
    pattern = rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']'
    match = re.search(pattern, page_html, flags=re.IGNORECASE)
    if not match:
        pattern_rev = rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']'
        match = re.search(pattern_rev, page_html, flags=re.IGNORECASE)
    return html_lib.unescape(match.group(1)).strip() if match else ""


def try_fetch_og_image(url: str) -> str | None:
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                img = _extract_meta(resp.text, "og:image")
                if img.startswith(("http://", "https://")):
                    return img
    except Exception:
        pass
    return None


HELP_TEXT = (
    "🏐 <b>Comandos do bot-ftv</b>\n\n"
    "<b>Publicar oferta manual:</b>\n"
    "<code>/postar Bola Mikasa FT-5 Oficial | 289,90 | 389,90 | https://seu-link</code>\n"
    "ou sem preço antigo:\n"
    "<code>/postar Rede Futevôlei Oficial | 149,90 | https://seu-link</code>\n\n"
    "💡 <i>Dica: você também pode enviar uma foto com esse comando na legenda!</i>\n\n"
    "<b>Status do bot:</b> <code>/status</code>"
)


def run_admin_listener(settings: Settings, db: Database, publisher: TelegramPublisher) -> None:
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        logger.warning("Listener /postar desativado: TELEGRAM_BOT_TOKEN ou TELEGRAM_ADMIN_CHAT_ID ausente.")
        return

    admin_id = str(settings.telegram_admin_chat_id)
    base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"
    offset = 0

    # Descarta updates antigos acumulados antes do boot
    try:
        with httpx.Client(timeout=15.0) as client:
            init_resp = client.get(f"{base_url}/getUpdates", params={"timeout": 0})
            if init_resp.status_code == 200:
                results = init_resp.json().get("result", [])
                if results:
                    offset = results[-1]["update_id"] + 1
    except Exception as exc:
        logger.warning("Nao foi possivel inicializar offset do Telegram: %s", exc)

    logger.info("Listener de comandos admin iniciado (chat_id=%s)", admin_id)

    while True:
        try:
            with httpx.Client(timeout=35.0) as client:
                resp = client.get(
                    f"{base_url}/getUpdates",
                    params={"offset": offset, "timeout": 25, "allowed_updates": '["message"]'},
                )
                resp.raise_for_status()
                updates = resp.json().get("result", [])

            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                if chat_id != admin_id:
                    continue

                text = (msg.get("text") or msg.get("caption") or "").strip()
                if not text:
                    continue

                photos = msg.get("photo") or []
                photo_file_id = photos[-1]["file_id"] if photos else None

                lower = text.lower()
                if lower.startswith(("/ajuda", "/help", "/start")):
                    publisher.notify_admin(HELP_TEXT)
                elif lower.startswith("/status"):
                    sent_today = db.count_sent_today()
                    stores = [
                        name
                        for name, enabled in [
                            ("Mercado Livre", settings.enable_mercadolivre),
                            ("Shopee", settings.enable_shopee),
                            ("Amazon", settings.enable_amazon),
                        ]
                        if enabled
                    ]
                    stores_label = ", ".join(stores) if stores else "Nenhuma (somente /postar manual)"
                    publisher.notify_admin(
                        f"✅ <b>bot-ftv online</b>\n"
                        f"Lojas automáticas: {stores_label}\n"
                        f"Ofertas postadas hoje: <b>{sent_today}/{settings.max_posts_per_day}</b>\n"
                        f"Canal destino: <code>{settings.telegram_channel_id}</code>"
                    )
                elif lower.startswith("/postar"):
                    try:
                        offer = parse_postar_command(text, photo_file_id=photo_file_id)
                        if not offer.image_url:
                            og_img = try_fetch_og_image(offer.url)
                            if og_img:
                                offer = Offer(**{**offer.__dict__, "image_url": og_img})
                        sent_today = db.count_sent_today()
                        publisher.send_offer(offer, variant_index=sent_today)
                        db.record_sent(offer)
                        publisher.notify_admin(f"✅ Publicado no canal: <b>{html_lib.escape(offer.title)}</b>")
                    except Exception as exc:
                        publisher.notify_admin(f"❌ Erro ao publicar:\n<code>{html_lib.escape(str(exc))}</code>")
        except Exception as exc:
            logger.error("Erro no loop de comandos Telegram: %s", exc)
            time.sleep(5)

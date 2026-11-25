import argparse
from datetime import datetime
import logging
import threading
import time

from src.collectors.amazon import AmazonCollector
from src.collectors.mercadolivre import MercadoLivreCollector
from src.collectors.shopee import ShopeeCollector
from src.config import Settings, load_rules, load_settings
from src.db import TZ, Database
from src.filters import filter_offers
from src.manual_bot import run_admin_listener
from src.models import Offer
from src.telegram import TelegramPublisher, format_offer_html

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot-ftv")


def is_within_active_window(settings: Settings, now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ)
    current = (now.hour, now.minute)
    start = (settings.active_start_hour, settings.active_start_minute)
    end = (settings.active_end_hour, settings.active_end_minute)
    return start <= current <= end


def build_collectors(settings: Settings) -> list:
    collectors = []
    if settings.enable_mercadolivre:
        collectors.append(
            MercadoLivreCollector(
                access_token=settings.ml_access_token,
                affiliate_param=settings.ml_affiliate_param,
            )
        )
    if settings.enable_shopee:
        collectors.append(
            ShopeeCollector(
                app_id=settings.shopee_app_id,
                app_secret=settings.shopee_app_secret,
            )
        )
    if settings.enable_amazon:
        collectors.append(
            AmazonCollector(
                access_key=settings.amazon_access_key,
                secret_key=settings.amazon_secret_key,
                partner_tag=settings.amazon_partner_tag,
            )
        )
    return collectors


def run_cycle(
    settings: Settings,
    db: Database,
    publisher: TelegramPublisher | None,
    failure_streaks: dict[str, int],
    dry_run: bool = False,
) -> dict[str, int]:
    started_at = datetime.now(TZ)
    rules = load_rules(settings.config_path)
    keywords = [kw for cat in rules.categories for kw in cat.keywords]
    collectors = build_collectors(settings)

    raw_offers: list[Offer] = []
    errors: list[str] = []

    for collector in collectors:
        try:
            fetched = collector.fetch(keywords)
            raw_offers.extend(fetched)
            failure_streaks[collector.name] = 0
        except Exception as exc:
            streak = failure_streaks.get(collector.name, 0) + 1
            failure_streaks[collector.name] = streak
            msg = f"{collector.name}: {exc}"
            errors.append(msg)
            logger.error("Coletor falhou (%dx): %s", streak, msg)
            if streak == 3 and publisher and not dry_run:
                publisher.notify_admin(f"⚠️ <b>bot-ftv</b>: coletor <code>{collector.name}</code> falhou 3x seguidas:\n<code>{exc}</code>")

    approved = filter_offers(raw_offers, rules)
    sent_today = db.count_sent_today(started_at)
    remaining_today = max(0, settings.max_posts_per_day - sent_today)
    budget = min(settings.max_posts_per_cycle, remaining_today)

    sent_count = 0
    for idx, offer in enumerate(approved):
        if sent_count >= budget:
            break
        if not db.can_send(offer, cooldown_days=settings.cooldown_days, now=started_at):
            continue

        if dry_run:
            logger.info("[DRY-RUN] Publicaria:\n%s\n", format_offer_html(offer, variant_index=idx))
            sent_count += 1
            continue

        if publisher is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN e TELEGRAM_CHANNEL_ID sao obrigatorios fora do --dry-run")

        try:
            publisher.send_offer(offer, variant_index=sent_today + sent_count)
            db.record_sent(offer, now=started_at)
            sent_count += 1
            time.sleep(2)
        except Exception as exc:
            errors.append(f"telegram({offer.external_id}): {exc}")
            logger.error("Erro ao publicar oferta %s: %s", offer.external_id, exc)

    finished_at = datetime.now(TZ)
    if not dry_run:
        db.record_run(
            started_at=started_at,
            finished_at=finished_at,
            fetched_count=len(raw_offers),
            approved_count=len(approved),
            sent_count=sent_count,
            error_count=len(errors),
            error_summary="; ".join(errors),
        )

    summary = {
        "fetched": len(raw_offers),
        "approved": len(approved),
        "sent": sent_count,
        "errors": len(errors),
    }
    logger.info("Ciclo finalizado: %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot de promocoes de Futevolei (MVP sem IA)")
    parser.add_argument("--once", action="store_true", help="Executa apenas 1 ciclo e encerra")
    parser.add_argument("--dry-run", action="store_true", help="Simula o ciclo sem publicar no Telegram nem gravar envios")
    parser.add_argument("--test-telegram", action="store_true", help="Envia mensagem de teste no Telegram e encerra")
    args = parser.parse_args()

    settings = load_settings()
    publisher = (
        TelegramPublisher(
            bot_token=settings.telegram_bot_token,
            channel_id=settings.telegram_channel_id,
            admin_chat_id=settings.telegram_admin_chat_id,
            channel_invite_url=settings.channel_invite_url,
        )
        if settings.telegram_bot_token and settings.telegram_channel_id
        else None
    )

    if args.test_telegram:
        if not settings.telegram_bot_token:
            raise SystemExit("Defina TELEGRAM_BOT_TOKEN no .env para testar o Telegram.")
        target = settings.telegram_admin_chat_id or settings.telegram_channel_id
        if not target:
            raise SystemExit("Defina TELEGRAM_ADMIN_CHAT_ID ou TELEGRAM_CHANNEL_ID no .env.")
        test_pub = TelegramPublisher(settings.telegram_bot_token, target, target)
        test_pub._post("sendMessage", {"chat_id": target, "text": "✅ bot-ftv conectado com sucesso!", "parse_mode": "HTML"})
        logger.info("Mensagem de teste enviada com sucesso para %s", target)
        return

    db = Database(settings.db_path)
    failure_streaks: dict[str, int] = {}

    if args.once or args.dry_run:
        run_cycle(settings, db, publisher, failure_streaks, dry_run=args.dry_run)
        return

    logger.info("bot-ftv iniciado (intervalo=%d min, janela=%02d:%02d-%02d:%02d)",
                settings.poll_interval_minutes,
                settings.active_start_hour, settings.active_start_minute,
                settings.active_end_hour, settings.active_end_minute)

    if publisher is not None:
        listener = threading.Thread(
            target=run_admin_listener,
            args=(settings, db, publisher),
            daemon=True,
            name="telegram-admin-listener",
        )
        listener.start()

    while True:
        if build_collectors(settings):
            if is_within_active_window(settings):
                run_cycle(settings, db, publisher, failure_streaks, dry_run=False)
            else:
                logger.info("Fora da janela ativa; aguardando proximo ciclo.")
        else:
            logger.info("Nenhuma loja automatica ativa; operando em modo /postar manual.")
        time.sleep(settings.poll_interval_minutes * 60)


if __name__ == "__main__":
    main()

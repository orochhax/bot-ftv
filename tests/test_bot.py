from datetime import datetime, timedelta
from pathlib import Path

from src.collectors.shopee import build_shopee_auth_header
from src.config import load_rules
from src.db import TZ, Database
from src.filters import filter_offers
from src.manual_bot import parse_postar_command
from src.models import Offer
from src.telegram import format_offer_html


def test_filter_approves_mikasa_and_blocks_replica_and_junk():
    rules = load_rules(Path("config/futevolei.json"))
    offers = [
        Offer(
            store="mercadolivre",
            external_id="MLB1",
            title="Bola de Futevôlei Mikasa FT-5 Oficial",
            price=299.90,
            old_price=399.90,
            url="https://example.com/1",
        ),
        Offer(
            store="mercadolivre",
            external_id="MLB2",
            title="Bola Mikasa FT-5 Réplica Primeira Linha",
            price=199.90,
            old_price=299.90,
            url="https://example.com/2",
        ),
        Offer(
            store="mercadolivre",
            external_id="MLB3",
            title="Bola Mikasa FT-5 suspeita muito barata",
            price=89.90,
            old_price=150.00,
            url="https://example.com/3",
        ),
        Offer(
            store="shopee",
            external_id="SH1",
            title="Chaveiro Bola Mikasa FT-5 Futevolei",
            price=29.90,
            old_price=50.00,
            url="https://example.com/4",
        ),
        Offer(
            store="shopee",
            external_id="SH2",
            title="Rede Futevôlei Oficial Fio 2mm",
            price=149.90,
            old_price=199.90,
            url="https://example.com/5",
        ),
    ]

    approved = filter_offers(offers, rules)
    assert [o.external_id for o in approved] == ["SH2", "MLB1"]
    assert approved[0].discount_pct == 25


def test_db_cooldown_and_extra_price_drop(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    now = datetime(2026, 11, 25, 10, 0, tzinfo=TZ)
    offer = Offer(
        store="shopee",
        external_id="ITEM123",
        title="Bola Mikasa FT-5",
        price=300.0,
        old_price=400.0,
        url="https://example.com/item",
    )

    assert db.can_send(offer, cooldown_days=7, now=now) is True
    db.record_sent(offer, now=now)

    # Mesmo preco no dia seguinte -> bloqueado
    assert db.can_send(offer, cooldown_days=7, now=now + timedelta(days=1)) is False
    # Queda adicional de 10% (300 -> 270) -> liberado
    cheaper = Offer(**{**offer.__dict__, "price": 270.0})
    assert db.can_send(cheaper, cooldown_days=7, now=now + timedelta(days=1)) is True
    # Apos 7 dias -> liberado
    assert db.can_send(offer, cooldown_days=7, now=now + timedelta(days=7)) is True
    assert db.count_sent_today(now) == 1


def test_shopee_signature_format():
    header = build_shopee_auth_header("12345", "secret", '{"query":"ok"}', 1700000000)
    assert header.startswith("SHA256 Credential=12345, Timestamp=1700000000, Signature=")
    assert len(header.split("Signature=")[1]) == 64


def test_telegram_html_escapes_special_chars():
    offer = Offer(
        store="mercadolivre",
        external_id="MLB99",
        title="Bola Mikasa <FT-5> & Rede",
        price=289.90,
        old_price=389.90,
        url="https://example.com/item?a=1&b=2",
    )
    msg = format_offer_html(offer, variant_index=0)
    assert "&lt;FT-5&gt; &amp; Rede" in msg
    assert "R$ 289,90" in msg
    assert "-26% OFF" in msg


def test_parse_postar_command_with_and_without_old_price():
    offer = parse_postar_command(
        "/postar Bola Mikasa FT-5 Oficial | 289,90 | 389,90 | https://mercadolivre.com/sec/abc123"
    )
    assert offer.store == "mercadolivre"
    assert offer.price == 289.90
    assert offer.old_price == 389.90
    assert offer.discount_pct == 26

    offer2 = parse_postar_command(
        "/postar Rede Futevôlei | 149.90 | https://amzn.to/xyz",
        photo_file_id="FILE123",
    )
    assert offer2.store == "amazon"
    assert offer2.old_price is None
    assert offer2.image_url == "FILE123"

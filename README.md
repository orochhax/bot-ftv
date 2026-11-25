# bot-ftv — Bot Automático de Promoções de Futevôlei (MVP Sem IA)

Bot em Python 3.12 + SQLite + Docker que busca ofertas de **Futevôlei** no **Mercado Livre**, **Shopee** e **Amazon**, filtra por regras determinísticas (sem IA) e publica no **Telegram**.

## Rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Preencha `.env` com suas credenciais e teste:

```bash
# Testes unitarios
pytest

# Simula 1 ciclo sem publicar no Telegram
python -m src.main --dry-run

# Testa envio no Telegram
python -m src.main --test-telegram

# Executa 1 ciclo real
python -m src.main --once
```

## Subir na VPS (Ubuntu + Docker)

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/orochhax/bot-ftv.git
cd bot-ftv
cp .env.example .env
nano .env   # preencher tokens e chaves
docker compose up -d --build
docker compose logs -f
```

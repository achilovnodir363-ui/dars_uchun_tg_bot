# Python Coding Arena — Telegram quiz bot

Texnologiyalar: python-telegram-bot 22.3, PostgreSQL (SQLAlchemy async + asyncpg). Python 3.10+.

## .env
- TOKEN — BotFather → /newbot
- ADMIN_ID — sizning Telegram ID (@userinfobot yoki bot logidagi `/start: user_id=...`)
- DATABASE_URL — postgresql+asyncpg://postgres:PAROL@localhost:5432/tg_bot

## Ishga tushirish (Windows)
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python smoke_db.py      # SMOKE OK chiqishi kerak
    python main.py

(Linux/macOS: `source .venv/bin/activate`)

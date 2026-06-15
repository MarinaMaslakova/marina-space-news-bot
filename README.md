# Космический дайджест (Space News Bot)

Короткий скрипт на Python, который собирает новые статьи из RSS-лент и отправляет вам на почту краткий дайджест.

Файлы:
- `bot.py` — основной скрипт.
- `requirements.txt` — зависимости.
- `railway.json` — конфиг для Railway (с `cron`).
- `.env.example` — пример переменных окружения.

Переменные окружения (используйте Railway Secrets или `.env` локально):

- `EMAIL_PROVIDER` — `smtp`, `resend` или `sendgrid`.
- `EMAIL_API_KEY` — ключ API для `resend` или `sendgrid`.
- `EMAIL_FROM` — адрес отправителя при API-отправке.
- `EMAIL_RECEIVER` — адрес получателя.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` — настройки SMTP, если используете `EMAIL_PROVIDER=smtp`.
- `CLAUDE_API_URL`, `CLAUDE_API_KEY` — (опционально) для улучшенных резюме через Claude.
- `DAYS_LOOKBACK` — сколько дней назад считать новые статьи (по умолчанию 3).

Установка и локальный запуск:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SMTP_USERNAME=... SMTP_PASSWORD=... EMAIL_RECEIVER=you@example.com
python3 bot.py
```

Деплой на Railway:
1. Инициализируйте git-репозиторий и запушьте проект на GitHub.
2. Создайте новый проект в Railway и подключите репозиторий.
3. В панели Railway добавьте Secrets (SMTP_PASSWORD, SMTP_USERNAME, EMAIL_RECEIVER, CLAUDE_API_KEY и т.д.).
4. Railway будет запускать скрипт по расписанию, заданному в `railway.json`.

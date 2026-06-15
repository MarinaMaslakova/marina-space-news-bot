#!/usr/bin/env python3
import os
import json
import time
from datetime import datetime, timedelta, timezone
import feedparser
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from requests.exceptions import HTTPError

# Configuration (can be overridden by env vars)
RSS_FEEDS = [
    "https://www.nasa.gov/rss/dyn/breaking_news.rss",
    "https://science.nasa.gov/rss.xml",
    "https://www.esa.int/rssfeed/Our_Activities/Space_Science_and_Exploration",
    "https://www.space.com/feeds/all",
]
DAYS = int(os.getenv("DAYS_LOOKBACK", "3"))
SEEN_FILE = os.getenv("SEEN_FILE", "seen.json")

CLAUDE_API_URL = os.getenv("CLAUDE_API_URL")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY")

EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp").lower()
EMAIL_API_KEY = os.getenv("EMAIL_API_KEY")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", SMTP_USERNAME)
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
EMAIL_FROM = os.getenv("EMAIL_FROM", EMAIL_SENDER)


def load_seen():
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False, indent=2)


def parse_item_date(item):
    # feedparser gives published_parsed as time.struct_time
    t = item.get("published_parsed") or item.get("updated_parsed")
    if not t:
        return None
    return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)


def summarize_text(text):
    text = (text or "").strip()
    if not text:
        return ""
    # Prefer using Claude if configured
    if CLAUDE_API_URL and CLAUDE_API_KEY:
        try:
            payload = {"text": f"Кратко резюмируй на русском:\n\n{text}"}
            headers = {"Authorization": f"Bearer {CLAUDE_API_KEY}", "Content-Type": "application/json"}
            resp = requests.post(CLAUDE_API_URL, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            # Try common response keys
            for key in ("summary", "result", "text", "completion"):
                if key in data:
                    return data[key]
            # Fallback: use first 300 chars of returned JSON string
            return str(data)[:300]
        except Exception:
            pass
    # Fallback simple truncation
    return (text.replace("\n", " ")[:400] + ("..." if len(text) > 400 else ""))


def collect_new_items():
    seen = load_seen()
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    new_items = []
    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception:
            continue
        for entry in feed.entries:
            item_id = entry.get("id") or entry.get("link") or entry.get("title")
            if not item_id or item_id in seen:
                continue
            dt = parse_item_date(entry)
            if dt and dt < cutoff:
                continue
            # Mark as new
            new_items.append({
                "id": item_id,
                "title": entry.get("title", "(no title)"),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", entry.get("description", "")),
            })
            seen.add(item_id)
    save_seen(seen)
    return new_items


def build_html(items):
    if not items:
        return "<p>Нет новых статей за указанный период.</p>"
    parts = ["<h2>Краткий дайджест космических новостей</h2>"]
    for it in items:
        summary = summarize_text(it.get("summary"))
        parts.append(f"<h3><a href=\"{it['link']}\">{it['title']}</a></h3>")
        parts.append(f"<p>{summary}</p>")
    parts.append("<hr><p>Скрипт автоматически сгенерирован и отправлен по расписанию.</p>")
    return "\n".join(parts)


def send_email(subject, html_body):
    if EMAIL_PROVIDER == "smtp":
        if not SMTP_PASSWORD or not EMAIL_RECEIVER or not SMTP_USERNAME:
            print("SMTP не настроен — пропускаю отправку письма.")
            return
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        part = MIMEText(html_body, "html", _charset="utf-8")
        msg.attach(part)
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        try:
            s.starttls()
            s.login(SMTP_USERNAME, SMTP_PASSWORD)
            s.sendmail(EMAIL_SENDER, [EMAIL_RECEIVER], msg.as_string())
            print("Письмо отправлено на", EMAIL_RECEIVER)
        finally:
            s.quit()
        return

    if EMAIL_PROVIDER == "resend":
        if not EMAIL_API_KEY or not EMAIL_FROM or not EMAIL_RECEIVER:
            print("Resend API не настроен — пропускаю отправку письма.")
            return
        url = "https://api.resend.com/emails"
        payload = {
            "from": EMAIL_FROM,
            "to": [EMAIL_RECEIVER],
            "subject": subject,
            "html": html_body,
        }
        headers = {
            "Authorization": f"Bearer {EMAIL_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        if resp.status_code >= 400:
            # Try to show helpful debug info
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            print(f"Resend API error: status={resp.status_code}")
            print("Response body:", body)

            # If domain isn't verified, optionally fall back to SendGrid when user provided SENDGRID_API_KEY
            msg = ""
            try:
                if isinstance(body, dict):
                    msg = body.get("message", "") or str(body)
                else:
                    msg = str(body)
            except Exception:
                msg = str(body)

            if resp.status_code == 403 and "domain is not verified" in msg.lower():
                sg_key = os.getenv("SENDGRID_API_KEY") or os.getenv("ALT_EMAIL_API_KEY")
                if sg_key:
                    print("Resend rejected: domain not verified. Falling back to SendGrid (SENDGRID_API_KEY detected).")
                    sg_url = "https://api.sendgrid.com/v3/mail/send"
                    sg_payload = {
                        "personalizations": [{"to": [{"email": EMAIL_RECEIVER}]}],
                        "from": {"email": EMAIL_FROM},
                        "subject": subject,
                        "content": [{"type": "text/html", "value": html_body}],
                    }
                    sg_headers = {"Authorization": f"Bearer {sg_key}", "Content-Type": "application/json"}
                    sg_resp = requests.post(sg_url, json=sg_payload, headers=sg_headers, timeout=30)
                    try:
                        sg_resp.raise_for_status()
                        print("Письмо отправлено через SendGrid (fallback) на", EMAIL_RECEIVER)
                        return
                    except HTTPError as exc2:
                        print("SendGrid fallback error:", exc2)
                        print("Response body:", sg_resp.text)
                        return
            # No fallback or fallback failed — give actionable guidance
            print("Подсказка: для Resend отправитель должен быть подтверждён в https://resend.com/domains")
            return
        try:
            resp.raise_for_status()
        except HTTPError as exc:
            # This branch is unlikely, but keep original error printing
            print("Resend API error:", exc)
            print("Response body:", resp.text)
            return
        print("Письмо отправлено на", EMAIL_RECEIVER)
        return

    if EMAIL_PROVIDER == "sendgrid":
        if not EMAIL_API_KEY or not EMAIL_FROM or not EMAIL_RECEIVER:
            print("SendGrid API не настроен — пропускаю отправку письма.")
            return
        url = "https://api.sendgrid.com/v3/mail/send"
        payload = {
            "personalizations": [{"to": [{"email": EMAIL_RECEIVER}]}],
            "from": {"email": EMAIL_FROM},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}],
        }
        headers = {
            "Authorization": f"Bearer {EMAIL_API_KEY}",
            "Content-Type": "application/json",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        try:
            resp.raise_for_status()
        except HTTPError as exc:
            print("SendGrid API error:", exc)
            print("Response body:", resp.text)
            return
        print("Письмо отправлено на", EMAIL_RECEIVER)
        return

    print(f"Неизвестный EMAIL_PROVIDER={EMAIL_PROVIDER}. Укажите smtp, resend или sendgrid.")


def main():
    items = collect_new_items()
    if not items:
        print("Нет новых статей.")
        return
    html = build_html(items)
    subject = f"Дайджест космических новостей — {datetime.now().date()}"
    send_email(subject, html)


if __name__ == "__main__":
    main()

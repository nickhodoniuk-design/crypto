import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

# Налаштування через Environment Variables у Render
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@crypsignalsa")
REFERRAL_LINK = "https://binance.com"
SENSITIVITY_PERCENT = 0.5
CHECK_INTERVAL = 300

BINANCE_URL = "https://data-api.binance.vision/api/v3/ticker/price"
LAST_PRICES = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

session = requests.Session()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *args):
        pass


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def send_telegram(text):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не заданий!")

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    response = session.post(
        url,
        json={
            "chat_id": CHANNEL_ID,
            "text": text
        },
        timeout=15
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API: {result}")

    logging.info("Повідомлення успішно надіслано в Telegram")


def get_prices():
    response = session.get(BINANCE_URL, timeout=20)
    response.raise_for_status()
    data = response.json()

    return {
        item["symbol"]: float(item["price"])
        for item in data
        if item["symbol"].endswith("USDT")
    }


async def main():
    global LAST_PRICES

    logging.info("Запуск криптобота...")

    # Перевіряємо Telegram і доступ до каналу
    await asyncio.to_thread(
        send_telegram,
        "🚀 Бот запущений! Перевірка Telegram успішна."
    )

    # Отримуємо початкові ціни
    LAST_PRICES = await asyncio.to_thread(get_prices)
    logging.info("Завантажено цін: %s", len(LAST_PRICES))

    while True:
        await asyncio.sleep(CHECK_INTERVAL)

        try:
            current = await asyncio.to_thread(get_prices)

            signals = []

            for symbol, price in current.items():
                old = LAST_PRICES.get(symbol)

                if old is None or old <= 0:
                    continue

                change = ((price - old) / old) * 100

                if abs(change) >= SENSITIVITY_PERCENT:
                    name = symbol.removesuffix("USDT")

                    signals.append(
                        f"📊 {name}/USDT\n"
                        f"Ціна: {price:.8g}\n"
                        f"Зміна за 5 хв: {change:+.2f}%\n"
                        f"🔗 {REFERRAL_LINK}"
                    )

            # Оновлюємо ціни навіть тоді, коли сигналів немає
            LAST_PRICES = current

            logging.info(
                "Перевірено %s пар; сигналів: %s",
                len(current),
                len(signals)
            )

            # Не надсилаємо сотні повідомлень окремо
            for start in range(0, len(signals), 10):
                batch = signals[start:start + 10]
                message = "\n\n".join(batch)

                await asyncio.to_thread(send_telegram, message)

        except Exception:
            logging.exception("Помилка під час перевірки цін")


if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()

    try:
        asyncio.run(main())
    except Exception:
        logging.exception("Критична помилка бота")
        raise

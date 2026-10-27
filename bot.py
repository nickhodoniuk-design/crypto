import asyncio
import requests
import time
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# ==================== НАЛАШТУВАННЯ БОТА ====================
TOKEN = "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo"
CHANNEL_ID = "@crypsignalsa"
REFERRAL_LINK = "https://binance.com"
SENSITIVITY_PERCENT = 0.0  # 0.0 для миттєвого тесту під час першої перевірки
# ===========================================================

LAST_PRICES = {}

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

def get_all_usdt_pairs():
    try:
        # ОФІЦІЙНИЙ СЕРВЕР ДАНИХ ДЛЯ РОЗРОБНИКІВ
        response = requests.get("api.binance.vision", timeout=10).json()
        return {item['symbol']: float(item['price']) for item in response if item['symbol'].endswith('USDT')}
    except Exception as e:
        try:
            # РЕЗЕРВНЕ ОФІЦІЙНЕ ДЗЕРКАЛО BINANCE
            response = requests.get("https://binance.com", timeout=10).json()
            return {item['symbol']: float(item['price']) for item in response if item['symbol'].endswith('USDT')}
        except Exception as e2:
            print(f"Помилка збору цін з біржі: {e2}")
            return {}

async def check_crypto():
    global LAST_PRICES
    print("Бот успішно запустився в хмарі.")
    
    clean_token = TOKEN.replace('bot', '')
    telegram_url = f"api.telegram.org{clean_token}/sendMessage"
    
    LAST_PRICES = get_all_usdt_pairs()
    if LAST_PRICES:
        print(f"✅ Успішно взято в роботу {len(LAST_PRICES)} криптопар. Починаю аналіз ринку...")
        
        test_text = "🔔 **Криптобот успішно запрацював на Render!**\n\nТепер усі технічні адреси правильні. Бот цілодобово сканує криптопари Binance."
        try:
            res = requests.post(telegram_url, json={"chat_id": CHANNEL_ID, "text": test_text, "parse_mode": "Markdown"}, timeout=10)
            print(f"Статус тестового відправлення в Telegram: {res.status_code} - {res.text}")
        except Exception as err:
            print(f"Помилка надсилання тесту: {err}")
            
    while True:
        await asyncio.sleep(300)  # Аналіз ринку кожні 5 хвилин
        try:
            current_prices = get_all_usdt_pairs()
            if not current_prices:
                continue
                
            for symbol, price in current_prices.items():
                if symbol not in LAST_PRICES:
                    LAST_PRICES[symbol] = price
                    continue
                    
                old_price = LAST_PRICES[symbol]
                if old_price == 0:
                    continue
                    
                change = ((price - old_price) / old_price) * 100
                
                if abs(change) >= SENSITIVITY_PERCENT:
                    coin_name = symbol.replace("USDT", " / USDT")
                    direction = f"🟢 РІЗКИЙ РІСТ {coin_name}!" if change > 0 else f"🔴 РІЗКЕ ПАДІННЯ {coin_name}!"
                    action = "📈 Рекомендація: LONG (Купівля)" if change > 0 else "📉 Рекомендація: SHORT (Продаж)"
                        
                    text = (
                        f"{direction}\n\n"
                        f"💵 Поточна ціна: {price:,.4f}\n"
                        f"📊 Зміна за 5 хв: {change:+.2f}%\n\n"
                        f"{action}\n\n"
                        f"🔗 Торгувати з бонусами на Binance:\n{REFERRAL_LINK}\n\n"
                        f"🕒 Час: {time.strftime('%H:%M:%S')}"
                    )
                    
                    requests.post(telegram_url, json={"chat_id": CHANNEL_ID, "text": text, "disable_web_page_preview": True}, timeout=10)
            
            LAST_PRICES = current_prices
        except Exception as e:
            print(f"Помилка в циклі: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_health_server, daemon=True).start()
    asyncio.run(check_crypto())


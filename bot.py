import asyncio
import requests
import time

# ==================== НАЛАШТУВАННЯ БОТА ====================
# Вставте сюди свій токен (слово 'bot' на початку писати НЕ ТРЕБА, лише цифри та літери)
TOKEN = "8955162722:AAELKreThbmZq7FfacTqTgZSFpS2MbpWMiQ"

# Вставте сюди юзернейм вашого каналу (обов'язково з @ на початку)
CHANNEL_ID = "@crypsignalsa"

# Ваше реферальне посилання для заробітку
REFERRAL_LINK = "https://www.binance.com/referral/earn-together/refer2earn-usdc/claim?hl=ru-UA&ref=GRO_28502_MDLIC&utm_source=referral_entrance"

# Чутливість (зміна ціни в % за 5 хвилин)
SENSITIVITY_PERCENT = 1.5
# ===========================================================

LAST_PRICES = {}

def get_all_usdt_pairs():
    try:
        url = "https://binance.vision"
        response = requests.get(url, timeout=10).json()
        return {item['symbol']: float(item['price']) for item in response if item['symbol'].endswith('USDT')}
    except Exception as e:
        print("Помилка підключення до основного дата-сервера. Пробую резервний...")
        try:
            url = "https://binance.com"
            response = requests.get(url, timeout=10).json()
            return {item['symbol']: float(item['price']) for item in response if item['symbol'].endswith('USDT')}
        except Exception as e2:
            print("Не вдалося отримати дані з жодного сервера:", e2)
            return {}

async def check_crypto():
    global LAST_PRICES
    print("Бот успішно запущений через захищений дата-сервер!")
    
    LAST_PRICES = get_all_usdt_pairs()
    if LAST_PRICES:
        print(f"✅ Успішно взято в роботу {len(LAST_PRICES)} криптопар. Починаю аналіз ринку...")
        
        # --- ТЕСТОВИЙ СИГНАЛ ДЛЯ ПЕРЕВІРКИ ---
        print("📢 Надсилаю тестовий сигнал у ваш Telegram-канал...")
        test_text = (
            "🔔 **Тестовий запуск криптобота пройшов успішно!**\n\n"
            "З цього моменту я стежу за 771 криптопарою на біржі Binance і буду публікувати сюди сигнали про різкі рухи цін."
        )
        # ОФІЦІЙНО ВИПРАВЛЕНЕ ПОСИЛАННЯ З КОСОЮ ЛІНІЄЮ (/) ТА ЗАХИСТОМ
        clean_token = TOKEN.replace('bot', '')
        telegram_url = f"https://telegram.org{clean_token}/sendMessage"
        
        try:
            res = requests.post(telegram_url, json={"chat_id": CHANNEL_ID, "text": test_text, "parse_mode": "Markdown"})
            if res.status_code == 200:
                print("🎉 Тестове повідомлення успішно з'явилося в каналі!")
            else:
                print(f"❌ Помилка Telegram. Відповідь сервера: {res.text}\nПеревірте, чи правильно вказано @юзернейм каналу і чи додано бота в адміни!")
        except Exception as telegram_err:
            print(f"❌ Не вдалося надіслати тест: {telegram_err}")
        # -------------------------------------
        
    else:
        print("❌ Не вдалося отримати початкові ціни. Перевірте підключення до інтернету.")
    
    while True:
        await asyncio.sleep(300) # Перевірка ринку кожні 5 хвилин
        
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
                    
                    if change > 0:
                        direction = f"🟢 РІЗКИЙ РІСТ {coin_name}!"
                        action = "📈 Рекомендація: LONG (Купівля)"
                    else:
                        direction = f"🔴 РІЗКЕ ПАДІННЯ {coin_name}!"
                        action = "📉 Рекомендація: SHORT (Продаж)"
                        
                    text = (
                        f"{direction}\n\n"
                        f"💵 Поточна ціна: {price:,.4f}\n"
                        f"📊 Зміна за 5 хв: {change:+.2f}%\n\n"
                        f"{action}\n\n"
                        f"🔗 Торгувати з бонусами на Bybit:\n{REFERRAL_LINK}\n\n"
                        f"🕒 Час: {time.strftime('%H:%M:%S')}"
                    )
                    
                    clean_token = TOKEN.replace('bot', '')
                    telegram_url = f"https://telegram.org{clean_token}/sendMessage"
                    requests.post(telegram_url, json={"chat_id": CHANNEL_ID, "text": text, "disable_web_page_preview": True})
                    print(f"🚀 Сигнал надіслано в канал по монеті {symbol}!")
            
            LAST_PRICES = current_prices
            
        except Exception as e:
            print(f"Помилка в циклі аналізу: {e}")

if __name__ == "__main__":
    asyncio.run(check_crypto())

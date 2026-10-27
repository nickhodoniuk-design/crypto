import time
import threading
from flask import Flask
import telebot
import ccxt
import pandas as pd
import pandas_ta as ta

# === НАСТРОЙКИ BOT / TELEGRAM ===
TELEGRAM_TOKEN = "ВАШ_ТЕЛЕГРАМ_ТОКЕН"
CHAT_ID = "ВАШ_ЧАТ_ИД"
TIMEFRAME = '15m'
# ================================

# Инициализация Flask веб-сервера для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает в фоновом режиме!", 200

bot = telebot.TeleBot(TELEGRAM_TOKEN)
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})

def get_all_futures_symbols():
    try:
        markets = exchange.load_markets()
        return [
            market['symbol'] for market in markets.values()
            if market['linear'] and market['active'] and market['settle'] == 'USDT'
        ]
    except Exception as e:
        print(f"Ошибка получения монет: {e}")
        return []

def get_market_data(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=60)
        if not ohlcv or len(ohlcv) < 30:
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        return df
    except Exception as e:
        return None

def check_signals():
    print("🚀 Начинаю сканирование рынка...")
    symbols = get_all_futures_symbols()
    for symbol in symbols:
        df = get_market_data(symbol, TIMEFRAME)
        if df is None or df.empty or 'rsi' not in df or 'atr' not in df:
            continue
            
        last_row = df.iloc[-1]
        current_price = float(last_row['close'])
        rsi_value = float(last_row['rsi'])
        atr_value = float(last_row['atr'])
        
        if pd.isna(rsi_value) or pd.isna(atr_value) or atr_value <= 0:
            continue

        if rsi_value <= 28:
            stop_loss = current_price - (atr_value * 1.5)
            take_profit = current_price + (atr_value * 3.0)
            message = (
                f"🟢 **СИГНАЛ: LONG (ПОКУПКА)** 🟢\n\n"
                f"🪙 Монета: `{symbol}`\n"
                f"💵 Цена входа: `{current_price}`\n"
                f"📊 RSI: {rsi_value:.2f}\n\n"
                f"🛑 Stop Loss: `{stop_loss:.4f}`\n"
                f"💰 Take Profit: `{take_profit:.4f}`\n"
            )
            try:
                bot.send_message(CHAT_ID, message, parse_mode='Markdown')
                time.sleep(1)
            except:
                pass
                
        elif rsi_value >= 72:
            stop_loss = current_price + (atr_value * 1.5)
            take_profit = current_price - (atr_value * 3.0)
            message = (
                f"🔴 **СИГНАЛ: SHORT (ПРОДАЖА)** 🔴\n\n"
                f"🪙 Монета: `{symbol}`\n"
                f"💵 Цена входа: `{current_price}`\n"
                f"📊 RSI: {rsi_value:.2f}\n\n"
                f"🛑 Stop Loss: `{stop_loss:.4f}`\n"
                f"💰 Take Profit: `{take_profit:.4f}`\n"
            )
            try:
                bot.send_message(CHAT_ID, message, parse_mode='Markdown')
                time.sleep(1)
            except:
                pass

def bot_loop():
    """Функция вечного цикла сканера рисков в отдельном потоке"""
    print("🤖 Поток сканера запущен успешно.")
    while True:
        try:
            check_signals()
            print("💤 Ожидание следующего цикла...")
            time.sleep(600)
        except Exception as e:
            print(f"Ошибка в цикле: {e}")
            time.sleep(60)

# Запуск сканирования рынка в отдельном фоновом потоке
threading.Thread(target=bot_loop, daemon=True).start()

# Основной поток Flask сервера для Render
if __name__ == "__main__":
    # Локально запускается на порту 5000, Render сам подставит нужный порт
    app.run(host='0.0.0.0', port=5000)

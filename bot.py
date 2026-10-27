import time
import threading
from flask import Flask
import telebot
import ccxt
import pandas as pd

# === НАСТРОЙКИ BOT / TELEGRAM ===
TELEGRAM_TOKEN = "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo"
CHAT_ID = "-1007810123995"
TIMEFRAME = '15m'
# ================================

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает в фоновом режиме!", 200

bot = telebot.TeleBot(TELEGRAM_TOKEN)
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})

def calculate_rsi(series, period=14):
    """Ручной расчет RSI без сторонних библиотек"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    """Ручной расчет ATR без сторонних библиотек"""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window=period).mean()

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
        
        # Считаем индикаторы нашими функциями
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['atr'] = calculate_atr(df, period=14)
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
    print("🤖 Поток сканера запущен успешно.")
    while True:
        try:
            check_signals()
            print("💤 Ожидание следующего цикла...")
            time.sleep(600)
        except Exception as e:
            print(f"Ошибка в цикле: {e}")
            time.sleep(60)

threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)

import time
import threading
from flask import Flask
import telebot
import ccxt
import pandas as pd

# === НАСТРОЙКИ BOT / TELEGRAM ===
TELEGRAM_TOKEN = "ВАШ_ТЕЛЕГРАМ_ТОКЕН"
CHAT_ID = "ВАШ_ЧАТ_ИД"
TIMEFRAME = '15m'  # Таймфрейм (15 минут)
# ================================

app = Flask(__name__)

@app.route('/')
def home():
    return "Бот Bybit работает в фоновом режиме!", 200

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Инициализируем биржу Bybit для работы с фьючерсами USDT
exchange = ccxt.bybit({
    'options': {'defaultType': 'linear'},  # Линейные фьючерсы (USDT)
    'enableRateLimit': True
})

def calculate_rsi(series, period=14):
    """Ручной расчет RSI"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    """Ручной расчет ATR"""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    return true_range.rolling(window=period).mean()

def get_all_futures_symbols():
    """Получение всех активных фьючерсных пар с Bybit"""
    try:
        markets = exchange.load_markets()
        symbols = [
            market['symbol'] for market in markets.values()
            if market['linear'] and market['active'] and market['settle'] == 'USDT'
        ]
        return symbols
    except Exception as e:
        print(f"Ошибка получения монет Bybit: {e}")
        return []

def get_market_data(symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=60)
        if not ohlcv or len(ohlcv) < 30:
            return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['rsi'] = calculate_rsi(df['close'], period=14)
        df['atr'] = calculate_atr(df, period=14)
        return df
    except Exception as e:
        return None

def check_signals():
    print("🚀 Начинаю сканирование фьючерсного рынка Bybit...")
    symbols = get_all_futures_symbols()
    print(f"Найдено монет на Bybit: {len(symbols)}")
    
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

        # Форматируем отображение имени монеты (делаем из BTC/USDT:USDT просто BTC/USDT)
        display_symbol = symbol.split(':')[0]

        # 🟢 LONG Сигнал
        if rsi_value <= 28:
            stop_loss = current_price - (atr_value * 1.5)
            take_profit = current_price + (atr_value * 3.0)
            message = (
                f"🟢 **СИГНАЛ Bybit: LONG (ПОКУПКА)** 🟢\n\n"
                f"🪙 Монета: `{display_symbol}`\n"
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
                
        # 🔴 SHORT Сигнал
        elif rsi_value >= 72:
            stop_loss = current_price + (atr_value * 1.5)
            take_profit = current_price - (atr_value * 3.0)
            message = (
                f"🔴 **СИГНАЛ Bybit: SHORT (ПРОДАЖА)** 🔴\n\n"
                f"🪙 Монета: `{display_symbol}`\n"
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
    print("🤖 Поток фонового сканера запущен.")
    while True:
        try:
            check_signals()
            print("💤 Ожидание следующего цикла сканирования...")
            time.sleep(600)
        except Exception as e:
            print(f"Ошибка в цикле: {e}")
            time.sleep(60)

# Запуск параллельного потока сканирования рынка
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)

import time
import telebot
import ccxt
import pandas as pd
import pandas_ta as ta

# === НАСТРОЙКИ BOT / TELEGRAM ===
TELEGRAM_TOKEN = "ВАШ_ТЕЛЕГРАМ_ТОКЕН"
CHAT_ID = "ВАШ_ЧАТ_ИД"
TIMEFRAME = '15m'  # Таймфрейм для анализа (15 минут)
# ================================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
# Инициализируем биржу Binance в режиме фьючерсов
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
    'enableRateLimit': True  # Защита от блокировки со стороны Binance API
})

def get_all_futures_symbols():
    """Автоматическое получение всех активных USDT фьючерсных пар"""
    try:
        markets = exchange.load_markets()
        # Фильтруем только активные линейные (USDT) фьючерсы
        symbols = [
            market['symbol'] for market in markets.values()
            if market['linear'] and market['active'] and market['settle'] == 'USDT'
        ]
        return symbols
    except Exception as e:
        print(f"Ошибка при получении списка монет: {e}")
        return []

def get_market_data(symbol, timeframe):
    """Получение исторических свечей и расчет индикаторов (RSI и ATR)"""
    try:
        # Запрашиваем 60 свечей (достаточно для расчета ATR-14 и RSI-14)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=60)
        if not ohlcv or len(ohlcv) < 30:
            return None
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Расчет технического индикатора RSI
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # Расчет индикатора волатильности ATR для динамического Stop Loss и Take Profit
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        return df
    except Exception as e:
        # Логируем ошибку (некоторые редкие пары могут выдавать ошибки API)
        print(f"Пропуск {symbol} (ошибка данных): {e}")
        return None

def check_signals():
    """Сканирование всего фьючерсного рынка и отправка сигналов"""
    print("🚀 Начинаю сканирование всех фьючерсных пар Binance...")
    symbols = get_all_futures_symbols()
    print(f"Найдено монет для анализа: {len(symbols)}")
    
    for symbol in symbols:
        df = get_market_data(symbol, TIMEFRAME)
        if df is None or df.empty or 'rsi' not in df or 'atr' not in df:
            continue
            
        # Берем последнюю закрытую свечу (индекс -1)
        last_row = df.iloc[-1]
        current_price = float(last_row['close'])
        rsi_value = float(last_row['rsi'])
        atr_value = float(last_row['atr'])
        
        # Проверяем, чтобы значения индикаторов были корректными числами
        if pd.isna(rsi_value) or pd.isna(atr_value) or atr_value <= 0:
            continue

        # === ЛОГИКА И СТРАТЕГИЯ СИГНАЛОВ ===
        
        # 🟢 Сигнал LONG (Перепроданность по RSI)
        if rsi_value <= 28:
            # Стоп-лосс ставится ниже цены на 1.5-кратный размер ATR
            stop_loss = current_price - (atr_value * 1.5)
            # Тейк-профит ставится выше цены на 3-кратный размер ATR (Риск/Прибыль = 1:2)
            take_profit = current_price + (atr_value * 3.0)
            
            message = (
                f"🟢 **СИГНАЛ: LONG (ПОКУПКА)** 🟢\n\n"
                f"🪙 Монета: `{symbol}`\n"
                f"💵 Цена входа: `{current_price}`\n"
                f"📊 Индикатор RSI: {rsi_value:.2f} (Перепроданность)\n\n"
                f"🎯 **УРОВНИ РИСКА:**\n"
                f"🛑 Stop Loss: `{stop_loss:.4f}`\n"
                f"💰 Take Profit: `{take_profit:.4f}`\n\n"
                f"⚠️ *Используйте правильный риск-менеджмент!*"
            )
            try:
                bot.send_message(CHAT_ID, message, parse_mode='Markdown')
                print(f"Отправлен LONG сигнал по {symbol}")
                time.sleep(1) # Небольшая пауза, чтобы Telegram не заблокировал за спам
            except Exception as tg_err:
                print(f"Ошибка отправки в Telegram: {tg_err}")
                
        # 🔴 Сигнал SHORT (Перекупленность по RSI)
        elif rsi_value >= 72:
            # Стоп-лосс ставится выше цены на 1.5-кратный размер ATR
            stop_loss = current_price + (atr_value * 1.5)
            # Тейк-профит ставится ниже цены на 3-кратный размер ATR
            take_profit = current_price - (atr_value * 3.0)
            
            message = (
                f"🔴 **СИГНАЛ: SHORT (ПРОДАЖА)** 🔴\n\n"
                f"🪙 Монета: `{symbol}`\n"
                f"💵 Цена входа: `{current_price}`\n"
                f"📊 Индикатор RSI: {rsi_value:.2f} (Перекупленность)\n\n"
                f"🎯 **УРОВНИ РИСКА:**\n"
                f"🛑 Stop Loss: `{stop_loss:.4f}`\n"
                f"💰 Take Profit: `{take_profit:.4f}`\n\n"
                f"⚠️ *Используйте правильный риск-менеджмент!*"
            )
            try:
                bot.send_message(CHAT_ID, message, parse_mode='Markdown')
                print(f"Отправлен SHORT сигнал по {symbol}")
                time.sleep(1)
            except Exception as tg_err:
                print(f"Ошибка отправки в Telegram: {tg_err}")

def main():
    print("🤖 Бот-сканер Binance запущен успешно.")
    while True:
        try:
            check_signals()
            # Интервал между полными циклами проверки рынка (например, каждые 10 минут)
            print("💤 Ожидание следующего цикла сканирования...")
            time.sleep(600)
        except Exception as e:
            print(f"Критическая ошибка в главном цикле: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()

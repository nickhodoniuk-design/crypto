import concurrent.futures
import html
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

# ============== НАСТРОЙКИ ==============

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@crypsignalsa")

BINANCE = "https://fapi.binance.com"
INTERVAL_SECONDS = 15 * 60
KLINE_INTERVAL = "15m"

EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
ATR_PERIOD = 14
VOLUME_PERIOD = 20

VOLUME_MULTIPLIER = 1.2
STOP_ATR = 1.5
TP1_ATR = 1.5
TP2_ATR = 3.0

MAX_WORKERS = 8
KLINE_LIMIT = 100
STATE_FILE = os.getenv("STATE_FILE", "state.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

thread_local = threading.local()
state_lock = threading.Lock()
stop_event = threading.Event()
last_processed = {}


# ============== HTTP ==============

def get_session():
    if not hasattr(thread_local, "session"):
        thread_local.session = requests.Session()
    return thread_local.session


def api_get(path, params=None):
    url = BINANCE + path

    for attempt in range(4):
        try:
            response = get_session().get(
                url, params=params, timeout=20
            )

            if response.status_code in (418, 429):
                delay = min(5 * (attempt + 1), 30)
                logging.warning(
                    "Binance rate limit: HTTP %s; retry in %ss",
                    response.status_code, delay,
                )
                time.sleep(delay)
                continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))

    raise RuntimeError("Binance API unavailable")


# ============== TELEGRAM ==============

def send_telegram(text):
    if not BOT_TOKEN:
        raise RuntimeError(
            "Укажите TELEGRAM_BOT_TOKEN в Render Environment"
        )

    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API: {result}")

    logging.info("Сообщение отправлено в Telegram")


# ============== СОСТОЯНИЕ И ДУБЛИКАТЫ ==============

def load_state():
    global last_processed

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            last_processed = json.load(file)
    except FileNotFoundError:
        last_processed = {}
    except (OSError, json.JSONDecodeError):
        logging.exception("Не удалось прочитать state.json")
        last_processed = {}


def save_state():
    temp_file = STATE_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(last_processed, file)
        os.replace(temp_file, STATE_FILE)
    except OSError:
        logging.exception(
            "Не удалось сохранить state.json"
        )


# ============== СПИСОК КОНТРАКТОВ ==============

def get_symbols():
    data = api_get("/fapi/v1/exchangeInfo")

    symbols = [
        item["symbol"]
        for item in data["symbols"]
        if item.get("status") == "TRADING"
        and item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
        and item.get("marginAsset") == "USDT"
    ]

    logging.info("Активных USDT perpetual-контрактов: %d", len(symbols))
    return symbols


# ============== СВЕЧИ ==============

def get_closed_candles(symbol):
    rows = api_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": KLINE_INTERVAL,
            "limit": KLINE_LIMIT,
        },
    )

    now_ms = int(time.time() * 1000)
    candles = []

    for row in rows:
        open_time = int(row[0])
        close_time = int(row[6])

        # Не используем свечу, которая ещё формируется.
        if close_time >= now_ms:
            continue

        candles.append({
            "time": open_time,
            "close_time": close_time,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })

    return candles


# ============== ИНДИКАТОРЫ ==============

def ema(values, period):
    """EMA с результатами, выровненными по исходным свечам."""
    result = [None] * len(values)

    if len(values) < period:
        return result

    current = sum(values[:period]) / period
    result[period - 1] = current
    alpha = 2 / (period + 1)

    for i in range(period, len(values)):
        current = values[i] * alpha + current * (1 - alpha)
        result[i] = current

    return result


def rsi(values, period=14):
    if len(values) <= period:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def atr(candles, period=14):
    if len(candles) <= period:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        candle = candles[i]
        previous_close = candles[i - 1]["close"]

        true_ranges.append(max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous_close),
            abs(candle["low"] - previous_close),
        ))

    recent = true_ranges[-period:]
    return sum(recent) / period


# ============== ФОРМАТИРОВАНИЕ ==============

def fmt_price(value):
    if value >= 1000:
        return f"{value:,.2f}".replace(",", " ")
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.6f}"
    return f"{value:.8f}"


def fmt_volume(value):
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} млрд"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} млн"
    if value >= 1000:
        return f"{value / 1000:.2f} тыс."
    return f"{value:.2f}"


# ============== СТРАТЕГИЯ ==============

def analyze(symbol, candles):
    required = max(
        EMA_SLOW + 2,
        RSI_PERIOD + 2,
        ATR_PERIOD + 2,
        VOLUME_PERIOD + 2,
    )

    if len(candles) < required:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    fast = ema(closes, EMA_FAST)
    slow = ema(closes, EMA_SLOW)

    last_index = len(candles) - 1
    candle = candles[last_index]

    if fast[last_index] is None or slow[last_index] is None:
        return None

    rsi_value = rsi(closes, RSI_PERIOD)
    atr_value = atr(candles, ATR_PERIOD)

    # Средний объём предыдущих свечей, без текущей.
    previous_volumes = volumes[-(VOLUME_PERIOD + 1):-1]
    avg_volume = sum(previous_volumes) / len(previous_volumes)

    if rsi_value is None or atr_value is None or atr_value <= 0:
        return None

    if avg_volume <= 0:
        return None

    volume_ratio = candle["volume"] / avg_volume

    bullish = (
        fast[last_index] > slow[last_index]
        and candle["close"] > fast[last_index]
        and 52 <= rsi_value <= 70
        and volume_ratio >= VOLUME_MULTIPLIER
    )

    bearish = (
        fast[last_index] < slow[last_index]
        and candle["close"] < fast[last_index]
        and 30 <= rsi_value <= 48
        and volume_ratio >= VOLUME_MULTIPLIER
    )

    if not bullish and not bearish:
        return None

    side = "LONG" if bullish else "SHORT"
    entry = candle["close"]

    if side == "LONG":
        stop = entry - STOP_ATR * atr_value
        tp1 = entry + TP1_ATR * atr_value
        tp2 = entry + TP2_ATR * atr_value
    else:
        stop = entry + STOP_ATR * atr_value
        tp1 = entry - TP1_ATR * atr_value
        tp2 = entry - TP2_ATR * atr_value

    risk = abs(entry - stop)
    reward = abs(tp2 - entry)

    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "rr": reward / risk if risk else 0,
        "rsi": rsi_value,
        "atr": atr_value,
        "volume_ratio": volume_ratio,
        "volume": candle["volume"],
        "change": (
            (candle["close"] - candle["open"])
            / candle["open"] * 100
        ),
        "candle_time": candle["time"],
        "close_time": candle["close_time"],
    }


# ============== СООБЩЕНИЕ ==============

def build_message(signal):
    symbol = html.escape(signal["symbol"])
    is_long = signal["side"] == "LONG"
    emoji = "🟢" if is_long else "🔴"
    direction = "ПОКУПКА — LONG" if is_long else "ПРОДАЖА — SHORT"

    closed_at = datetime.fromtimestamp(
        signal["close_time"] / 1000,
        tz=timezone.utc,
    ).strftime("%d.%m.%Y %H:%M UTC")

    chart = f"https://www.binance.com/en/futures/{signal['symbol']}"

    return (
        f"{emoji} <b>FUTURES СИГНАЛ | {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏱ <b>Таймфрейм:</b> 15 минут\n"
        f"📌 <b>Направление:</b> {direction}\n"
        f"💰 <b>Цена на закрытии:</b> {fmt_price(signal['entry'])} USDT\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛑 <b>Stop-Loss:</b> {fmt_price(signal['stop'])}\n"
        f"🎯 <b>Take-Profit 1:</b> {fmt_price(signal['tp1'])}\n"
        f"🎯 <b>Take-Profit 2:</b> {fmt_price(signal['tp2'])}\n"
        f"⚖️ <b>Риск/прибыль до TP2:</b> 1:{signal['rr']:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>АНАЛИЗ</b>\n"
        f"• EMA 9/21: тренд подтверждён\n"
        f"• RSI (14): {signal['rsi']:.1f}\n"
        f"• Объём к среднему: {signal['volume_ratio']:.2f}x\n"
        f"• ATR (14): {fmt_price(signal['atr'])}\n"
        f"• Изменение свечи: {signal['change']:+.2f}%\n"
        f"• Объём свечи: {fmt_volume(signal['volume'])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <b>Свеча закрыта:</b> {closed_at}\n"
        f"📈 <a href=\"{chart}\">Открыть график Binance Futures</a>\n\n"
        f"⚠️ <i>Сигнал основан на технических индикаторах. "
        f"Не является гарантией прибыли. Учитывайте комиссии, "
        f"проскальзывание и риск ликвидации.</i>"
    )


# ============== СКАНИРОВАНИЕ ==============

def scan_symbol(symbol):
    candles = get_closed_candles(symbol)

    if not candles:
        return None, None

    latest = candles[-1]
    candle_id = latest["time"]

    with state_lock:
        previous_id = last_processed.get(symbol)

    if previous_id == candle_id:
        return symbol, None

    signal = analyze(symbol, candles)

    # Сохраняем время проверенной свечи и без сигнала,
    # чтобы не обрабатывать её повторно в том же цикле.
    return symbol, {
        "candle_id": candle_id,
        "signal": signal,
    }


def seconds_to_next_candle():
    now = time.time()
    next_boundary = (int(now // INTERVAL_SECONDS) + 1) * INTERVAL_SECONDS
    return max(2, next_boundary - now + 3)


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN в Render Environment"
        )

    load_state()

    send_telegram(
        "🚀 <b>FUTURES SIGNAL BOT ЗАПУЩЕН</b>\n\n"
        "📊 Рынок: Binance USDⓈ-M Futures\n"
        "⏱ Таймфрейм: 15 минут\n"
        "📈 Стратегия: EMA 9/21 + RSI 14 + объём\n"
        "🟢 LONG / 🔴 SHORT\n"
        "🛡 Анализ только закрытых свечей."
    )

    symbols = get_symbols()

    send_telegram(
        f"✅ <b>МОНИТОРИНГ АКТИВЕН</b>\n"
        f"USDT perpetual-пар: {len(symbols)}\n"
        f"Порог объёма: {VOLUME_MULTIPLIER}x\n"
        f"Сканирование: после закрытия свечи."
    )

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        while not stop_event.is_set():
            delay = seconds_to_next_candle()
            logging.info("Следующее сканирование через %.1f сек.", delay)

            if stop_event.wait(delay):
                break

            try:
                symbols = get_symbols()
            except Exception:
                logging.exception("Не удалось обновить список контрактов")

            futures = {
                executor.submit(scan_symbol, symbol): symbol
                for symbol in symbols
            }

            signals = []

            for future in concurrent.futures.as_completed(futures):
                symbol = futures[future]

                try:
                    result_symbol, result = future.result()
                except Exception:
                    logging.exception("Ошибка сканирования %s", symbol)
                    continue

                if not result:
                    continue

                with state_lock:
                    last_processed[result_symbol] = result["candle_id"]

                signal = result["signal"]
                if signal:
                    signals.append(signal)

            with state_lock:
                save_state()

            signals.sort(
                key=lambda item: item["volume_ratio"],
                reverse=True,
            )

            logging.info(
                "Проверено пар: %d; найдено сигналов: %d",
                len(symbols), len(signals),
            )

            for signal in signals:
                try:
                    send_telegram(build_message(signal))
                    time.sleep(1)
                except Exception:
                    logging.exception(
                        "Ошибка отправки сигнала %s",
                        signal["symbol"],
                    )


if __name__ == "__main__":
    main()

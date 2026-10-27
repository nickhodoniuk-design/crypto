
import concurrent.futures
import html
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

# ---------- НАСТРОЙКИ ----------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8955162722:AAHxL1wUUNMn6V8a_qZZnemEpEBD9U05tgo")
CHAT_ID = os.getenv("CHANNEL_ID", "@crypsignalsa")
API = os.getenv("FUTURES_API_BASE", "https://fapi.binance.com").rstrip("/")
STATE_FILE = os.getenv("STATE_FILE", "state.json")

INTERVAL = "15m"
INTERVAL_SEC = 900
EMA_FAST = 9
EMA_SLOW = 21
RSI_PERIOD = 14
ATR_PERIOD = 14
VOLUME_PERIOD = 20
VOLUME_MULTIPLIER = 1.2

MAX_WORKERS = 6
RETRY_SECONDS = 60
KLINE_LIMIT = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

local = threading.local()
lock = threading.Lock()
processed = {}


# ---------- HTTP ----------
def session():
    if not hasattr(local, "session"):
        local.session = requests.Session()
        local.session.headers["User-Agent"] = "FuturesSignalBot/1.0"
    return local.session


def api_get(path, params=None):
    for attempt in range(3):
        try:
            response = session().get(
                API + path, params=params, timeout=20
            )

            if response.status_code == 451:
                raise RuntimeError(
                    "HTTP 451: Binance Futures API недоступен "
                    "из этого окружения. Требуется разрешённый "
                    "источник Futures-данных."
                )

            if response.status_code == 403:
                raise RuntimeError("HTTP 403: доступ запрещён.")

            if response.status_code == 429:
                time.sleep(10 * (attempt + 1))
                continue

            response.raise_for_status()
            return response.json()

        except RuntimeError:
            raise
        except (requests.RequestException, ValueError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Ошибка API: {exc}") from exc
            time.sleep(2 * (attempt + 1))

    raise RuntimeError("API недоступен после повторных попыток.")


# ---------- TELEGRAM ----------
def send_message(text):
    if not TOKEN:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN.")

    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    response.raise_for_status()

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Ошибка Telegram: {result}")


# ---------- ЗАЩИТА ОТ ДУБЛЕЙ ----------
def load_state():
    global processed
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            processed = data if isinstance(data, dict) else {}
    except FileNotFoundError:
        processed = {}
    except (OSError, json.JSONDecodeError):
        logging.exception("Не удалось загрузить состояние.")
        processed = {}


def save_state():
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(processed, f)
        os.replace(tmp, STATE_FILE)
    except OSError:
        logging.exception("Не удалось сохранить состояние.")


def is_processed(symbol, candle_time):
    with lock:
        return processed.get(symbol) == candle_time


def mark_processed(symbol, candle_time):
    with lock:
        processed[symbol] = candle_time
        save_state()


# ---------- РЫНОК ----------
def get_symbols():
    data = api_get("/fapi/v1/exchangeInfo")

    symbols = [
        item["symbol"]
        for item in data.get("symbols", [])
        if item.get("status") == "TRADING"
        and item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
        and item.get("marginAsset") == "USDT"
    ]

    if not symbols:
        raise RuntimeError("API не вернул активные USDT-контракты.")

    return symbols


def get_candles(symbol):
    rows = api_get(
        "/fapi/v1/klines",
        {"symbol": symbol, "interval": INTERVAL, "limit": KLINE_LIMIT},
    )

    now_ms = int(time.time() * 1000)
    candles = []

    for row in rows:
        # Не анализируем незакрытую свечу.
        if int(row[6]) >= now_ms:
            continue

        candles.append({
            "time": int(row[0]),
            "close_time": int(row[6]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })

    return candles


# ---------- ИНДИКАТОРЫ ----------
def ema(values, period):
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

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def atr(candles, period=14):
    if len(candles) <= period:
        return None

    ranges = []
    for i in range(1, len(candles)):
        c = candles[i]
        previous_close = candles[i - 1]["close"]

        ranges.append(max(
            c["high"] - c["low"],
            abs(c["high"] - previous_close),
            abs(c["low"] - previous_close),
        ))

    recent = ranges[-period:]
    return sum(recent) / len(recent)


# ---------- ФОРМАТ ЦЕН ----------
def price(value):
    if value >= 1000:
        return f"{value:,.2f}".replace(",", " ")
    if value >= 1:
        return f"{value:.4f}"
    if value >= 0.01:
        return f"{value:.6f}"
    return f"{value:.8f}"


def volume_text(value):
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} млрд"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} млн"
    if value >= 1000:
        return f"{value / 1000:.2f} тыс."
    return f"{value:.2f}"


# ---------- СТРАТЕГИЯ ----------
def analyze(symbol, candles):
    required = max(EMA_SLOW + 2, RSI_PERIOD + 2,
                   ATR_PERIOD + 2, VOLUME_PERIOD + 2)

    if len(candles) < required:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]

    fast = ema(closes, EMA_FAST)
    slow = ema(closes, EMA_SLOW)
    i = len(candles) - 1
    candle = candles[i]

    rsi_value = rsi(closes, RSI_PERIOD)
    atr_value = atr(candles, ATR_PERIOD)

    previous_volumes = volumes[-(VOLUME_PERIOD + 1):-1]
    avg_volume = sum(previous_volumes) / len(previous_volumes)

    if (
        fast[i] is None or slow[i] is None
        or rsi_value is None or atr_value is None
        or atr_value <= 0 or avg_volume <= 0
    ):
        return None

    volume_ratio = candle["volume"] / avg_volume

    long_signal = (
        fast[i] > slow[i]
        and candle["close"] > fast[i]
        and 52 <= rsi_value <= 70
        and volume_ratio >= VOLUME_MULTIPLIER
    )

    short_signal = (
        fast[i] < slow[i]
        and candle["close"] < fast[i]
        and 30 <= rsi_value <= 48
        and volume_ratio >= VOLUME_MULTIPLIER
    )

    if not long_signal and not short_signal:
        return None

    side = "LONG" if long_signal else "SHORT"
    entry = candle["close"]

    if side == "LONG":
        stop = entry - 1.5 * atr_value
        tp1 = entry + 1.5 * atr_value
        tp2 = entry + 3.0 * atr_value
    else:
        stop = entry + 1.5 * atr_value
        tp1 = entry - 1.5 * atr_value
        tp2 = entry - 3.0 * atr_value

    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "rsi": rsi_value,
        "atr": atr_value,
        "volume_ratio": volume_ratio,
        "volume": candle["volume"],
        "change": (candle["close"] - candle["open"])
                   / candle["open"] * 100,
        "candle_time": candle["time"],
        "close_time": candle["close_time"],
    }


# ---------- СООБЩЕНИЕ ----------
def build_message(s):
    symbol = html.escape(s["symbol"])
    is_long = s["side"] == "LONG"
    emoji = "🟢" if is_long else "🔴"
    direction = "ПОКУПКА — LONG" if is_long else "ПРОДАЖА — SHORT"

    closed_at = datetime.fromtimestamp(
        s["close_time"] / 1000, tz=timezone.utc
    ).strftime("%d.%m.%Y %H:%M UTC")

    chart = f"https://www.binance.com/en/futures/{s['symbol']}"

    return (
        f"{emoji} <b>FUTURES СИГНАЛ | {symbol}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏱ <b>Таймфрейм:</b> 15 минут\n"
        f"📌 <b>Направление:</b> {direction}\n"
        f"💰 <b>Цена закрытия:</b> {price(s['entry'])} USDT\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛑 <b>Stop-Loss:</b> {price(s['stop'])}\n"
        f"🎯 <b>Take-Profit 1:</b> {price(s['tp1'])}\n"
        f"🎯 <b>Take-Profit 2:</b> {price(s['tp2'])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>АНАЛИЗ РЫНКА</b>\n"
        f"• EMA 9/21: тренд подтверждён\n"
        f"• RSI (14): {s['rsi']:.1f}\n"
        f"• Объём к среднему: {s['volume_ratio']:.2f}x\n"
        f"• ATR (14): {price(s['atr'])}\n"
        f"• Изменение свечи: {s['change']:+.2f}%\n"
        f"• Объём свечи: {volume_text(s['volume'])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕒 <b>Свеча закрыта:</b> {closed_at}\n"
        f"📈 <a href=\"{chart}\">Открыть график Binance Futures</a>\n\n"
        f"⚠️ <i>Сигнал не гарантирует прибыль. "
        f"Учитывайте комиссии, проскальзывание и риск ликвидации.</i>"
    )


# ---------- СКАНИРОВАНИЕ ----------
def scan_symbol(symbol):
    candles = get_candles(symbol)
    if not candles:
        return None

    latest = candles[-1]
    candle_time = latest["time"]

    if is_processed(symbol, candle_time):
        return None

    signal = analyze(symbol, candles)

    return {
        "symbol": symbol,
        "candle_time": candle_time,
        "signal": signal,
    }


def wait_until_next_candle():
    now = time.time()
    next_candle = (int(now // INTERVAL_SEC) + 1) * INTERVAL_SEC
    return max(2, next_candle - now + 3)


# ---------- ОСНОВНОЙ ЦИКЛ ----------
def main():
    if not TOKEN:
        raise RuntimeError("Укажите TELEGRAM_BOT_TOKEN в Render.")

    load_state()

    try:
        send_message(
            "🚀 <b>FUTURES SIGNAL BOT ЗАПУЩЕН</b>\n\n"
            "⏱ Таймфрейм: 15 минут\n"
            "📊 EMA 9/21 + RSI 14 + объём\n"
            "🟢 LONG / 🔴 SHORT\n"
            "🛡 Только закрытые свечи."
        )
    except Exception:
        logging.exception("Не удалось отправить стартовое сообщение.")

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as pool:

        while True:
            try:
                symbols = get_symbols()
                logging.info("Найдено USDT perpetual-пар: %d", len(symbols))
            except Exception as exc:
                logging.error("Рынок недоступен: %s", exc)
                time.sleep(RETRY_SECONDS)
                continue

            time.sleep(wait_until_next_candle())

            futures = [
                pool.submit(scan_symbol, symbol)
                for symbol in symbols
            ]

            signals = []

            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    logging.warning("Ошибка сканирования: %s", exc)
                    continue

                if result is None:
                    continue

                symbol = result["symbol"]
                candle_time = result["candle_time"]

                # Запоминаем обработанную свечу даже без сигнала.
                mark_processed(symbol, candle_time)

                if result["signal"] is not None:
                    signals.append(result["signal"])

            signals.sort(
                key=lambda s: s["volume_ratio"],
                reverse=True,
            )

            logging.info(
                "Сканирование завершено. Сигналов: %d",
                len(signals),
            )

            for signal in signals:
                try:
                    send_message(build_message(signal))
                    time.sleep(1)
                except Exception:
                    logging.exception(
                        "Не удалось отправить сигнал %s",
                        signal["symbol"],
                    )


if __name__ == "__main__":
    main()

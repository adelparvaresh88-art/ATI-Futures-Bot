import os
import time
import hmac
import hashlib
import requests
from datetime import datetime, timezone

# ============================================================
# ATI FUTURES V1
# Tabdeal Futures | PAPER | MACD 12/26/9 | 5m
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BASE_URLS = [
    "https://api1.tabdeal.org",
    "https://api.tabdeal.org",
]

INTERVAL = "5m"
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

MAX_MARKETS = 30
KLINE_LIMIT = 100
REQUEST_TIMEOUT = 15

PAPER_MODE = True
LEVERAGE = 3
MARGIN_USDT = 2.0

# ------------------------------------------------------------
# Telegram
# ------------------------------------------------------------

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram: credentials missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        if r.ok:
            return True

        print("Telegram error:", r.status_code, r.text[:300])
        return False

    except Exception as e:
        print("Telegram exception:", e)
        return False


# ------------------------------------------------------------
# HTTP helpers
# ------------------------------------------------------------

def get_request(path, params=None):
    last_error = None

    for base in BASE_URLS:
        url = base.rstrip("/") + path

        try:
            r = requests.get(
                url,
                params=params or {},
                timeout=REQUEST_TIMEOUT,
            )

            print(f"GET {url} -> {r.status_code}")

            if r.status_code == 200:
                return r.json()

            last_error = f"{r.status_code}: {r.text[:200]}"

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(last_error or "HTTP request failed")


# ------------------------------------------------------------
# Tabdeal Futures exchange information
# ------------------------------------------------------------

def get_exchange_info():
    paths = [
        "/r/fapi/v1/exchangeInfo",
        "/fapi/v1/exchangeInfo",
    ]

    last_error = None

    for path in paths:
        try:
            data = get_request(path)

            if isinstance(data, dict) and "symbols" in data:
                return data

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(
        "Could not read Futures exchangeInfo: "
        + str(last_error)
    )


def get_markets():
    data = get_exchange_info()

    symbols = data.get("symbols", [])

    result = []

    for item in symbols:
        symbol = str(item.get("symbol", "")).upper()
        status = str(item.get("status", "")).upper()
        quote = str(item.get("quoteAsset", "")).upper()

        if not symbol:
            continue

        if status and status != "TRADING":
            continue

        if quote and quote != "USDT":
            continue

        if not symbol.endswith("USDT"):
            continue

        # Remove duplicate symbols
        if symbol not in result:
            result.append(symbol)

    result.sort()

    return result[:MAX_MARKETS]


# ------------------------------------------------------------
# Klines
# ------------------------------------------------------------

def get_klines(symbol):
    paths = [
        "/r/fapi/v1/klines",
        "/fapi/v1/klines",
    ]

    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": KLINE_LIMIT,
    }

    for path in paths:
        try:
            data = get_request(path, params)

            if isinstance(data, list) and len(data) > 0:
                return data

        except Exception as e:
            print(f"Klines failed {symbol} {path}: {e}")

    return []


def extract_closes(raw):
    closes = []

    if not isinstance(raw, list):
        return closes

    for candle in raw:
        try:
            # Binance-compatible candle:
            # 0 open time
            # 1 open
            # 2 high
            # 3 low
            # 4 close
            close_price = float(candle[4])
            closes.append(close_price)
        except Exception:
            continue

    return closes


# ------------------------------------------------------------
# EMA / MACD
# ------------------------------------------------------------

def ema(values, period):
    if len(values) < period:
        return []

    multiplier = 2.0 / (period + 1)

    result = []

    first = sum(values[:period]) / period
    result.append(first)

    previous = first

    for price in values[period:]:
        current = (
            (price - previous) * multiplier
            + previous
        )

        result.append(current)
        previous = current

    return result


def calculate_macd(closes):
    if len(closes) < MACD_SLOW + MACD_SIGNAL + 5:
        return None

    fast = ema(closes, MACD_FAST)
    slow = ema(closes, MACD_SLOW)

    if not fast or not slow:
        return None

    # Align fast EMA with slow EMA
    offset = MACD_SLOW - MACD_FAST

    if len(fast) <= offset:
        return None

    fast_aligned = fast[offset:]

    count = min(len(fast_aligned), len(slow))

    fast_aligned = fast_aligned[-count:]
    slow = slow[-count:]

    macd_line = [
        f - s
        for f, s in zip(fast_aligned, slow)
    ]

    signal_line = ema(
        macd_line,
        MACD_SIGNAL
    )

    if len(signal_line) < 2:
        return None

    # Align MACD with signal
    macd_for_signal = macd_line[-len(signal_line):]

    if len(macd_for_signal) < 2:
        return None

    macd_previous = macd_for_signal[-2]
    macd_current = macd_for_signal[-1]

    signal_previous = signal_line[-2]
    signal_current = signal_line[-1]

    histogram_current = (
        macd_current - signal_current
    )

    return {
        "macd": macd_current,
        "signal": signal_current,
        "histogram": histogram_current,
        "previous_macd": macd_previous,
        "previous_signal": signal_previous,
    }


# ------------------------------------------------------------
# Signal
# ------------------------------------------------------------

def get_signal(macd):
    if not macd:
        return None

    bullish_cross = (
        macd["previous_macd"]
        <= macd["previous_signal"]
        and
        macd["macd"]
        > macd["signal"]
    )

    bearish_cross = (
        macd["previous_macd"]
        >= macd["previous_signal"]
        and
        macd["macd"]
        < macd["signal"]
    )

    if bullish_cross:
        return "BUY"

    if bearish_cross:
        return "SELL"

    return None


# ------------------------------------------------------------
# Main scanner
# ------------------------------------------------------------

def run():
    started = time.time()

    print("=" * 60)
    print("ATI FUTURES V1")
    print("Exchange: Tabdeal Futures")
    print("Mode: PAPER")
    print("MACD: 12/26/9")
    print("Timeframe: 5m")
    print("Leverage: 3x")
    print("Margin: 2 USDT")
    print("=" * 60)

    if not API_KEY:
        print("WARNING: TABDEAL_API_KEY is missing")

    if not API_SECRET:
        print("WARNING: TABDEAL_API_SECRET is missing")

    try:
        markets = get_markets()
    except Exception as e:
        message = (
            "❌ ATI FUTURES\n\n"
            "ExchangeInfo failed.\n"
            f"Error: {e}"
        )

        print(message)
        telegram(message)
        return

    print(f"Markets found: {len(markets)}")

    ready = 0
    signals = []

    checked = 0
    errors = 0

    for symbol in markets:

        checked += 1

        try:
            raw = get_klines(symbol)

            closes = extract_closes(raw)

            if len(closes) < 40:
                print(
                    f"{symbol}: insufficient candles "
                    f"({len(closes)})"
                )
                continue

            ready += 1

            macd = calculate_macd(closes)

            if not macd:
                continue

            signal = get_signal(macd)

            print(
                f"{symbol} | "
                f"MACD={macd['macd']:.8f} | "
                f"Signal={macd['signal']:.8f} | "
                f"Hist={macd['histogram']:.8f} | "
                f"Signal={signal or '-'}"
            )

            if signal:
                signals.append({
                    "symbol": symbol,
                    "signal": signal,
                    "macd": macd["macd"],
                    "signal_line": macd["signal"],
                    "histogram": macd["histogram"],
                })

        except Exception as e:
            errors += 1
            print(f"{symbol}: ERROR: {e}")

        # Avoid hammering the API
        time.sleep(0.15)

    runtime = time.time() - started

    print("=" * 60)
    print(f"Markets: {len(markets)}")
    print(f"Checked: {checked}")
    print(f"MACD ready: {ready}")
    print(f"Signals: {len(signals)}")
    print(f"Errors: {errors}")
    print(f"Runtime: {runtime:.1f}s")
    print("=" * 60)

    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    if signals:
        text = (
            "🚨 ATI FUTURES V1\n\n"
            "🟢 PAPER MODE\n"
            "Exchange: Tabdeal Futures\n"
            "MACD: 12/26/9\n"
            "Timeframe: 5m\n\n"
        )

        for item in signals[:5]:
            text += (
                f"📊 {item['symbol']}\n"
                f"Signal: {item['signal']}\n"
                f"MACD: {item['macd']:.8f}\n"
                f"Signal: {item['signal_line']:.8f}\n"
                f"Histogram: {item['histogram']:.8f}\n\n"
            )

        text += f"Time: {now}"

    else:
        text = (
            "🤖 ATI FUTURES V1\n\n"
            "🟢 PAPER MODE\n"
            "Exchange: Tabdeal Futures\n"
            "MACD: 12/26/9\n"
            "Timeframe: 5m\n\n"
            f"Markets: {len(markets)}\n"
            f"MACD ready: {ready}\n"
            f"Signals: 0\n"
            f"Errors: {errors}\n"
            f"Runtime: {runtime:.1f}s\n\n"
            f"Time: {now}"
        )

    telegram(text)


if __name__ == "__main__":
    run()

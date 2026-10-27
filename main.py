import os
import time
import hmac
import hashlib
import requests
from datetime import datetime, timezone


# ============================================================
# ATI FUTURES BOT V5
# Tabdeal Futures | PAPER | MACD 12/26/9 | 5m
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BASE_URL = "https://api1.tabdeal.org"

INTERVAL = "5m"

MAX_MARKETS = 30
KLINE_LIMIT = 200
REQUEST_TIMEOUT = 15

FAST_PERIOD = 12
SLOW_PERIOD = 26
SIGNAL_PERIOD = 9

PAPER_MODE = True
REAL_TRADING = False

LEVERAGE = 3
MARGIN_USDT = 2.0

TP_PCT = 0.02
SL_PCT = 0.01


session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/5.0",
    "Accept": "application/json",
})


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def send_telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram: credentials not configured")
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print(
            f"Telegram HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )

        return False

    except Exception as exc:
        print(
            f"Telegram error: {str(exc)[:200]}"
        )
        return False


# ============================================================
# GENERIC GET
# ============================================================

def api_get(path, params=None):

    url = BASE_URL + path

    try:

        response = session.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            print(
                f"GET {path} -> "
                f"HTTP {response.status_code}"
            )
            return None

        try:
            return response.json()

        except Exception:
            print(
                f"GET {path} -> invalid JSON"
            )
            return None

    except requests.RequestException as exc:

        print(
            f"GET {path} -> "
            f"{str(exc)[:150]}"
        )

        return None


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    paths = [
        "/r/fapi/v1/exchangeInfo",
        "/fapi/v1/exchangeInfo",
    ]

    for path in paths:

        data = api_get(path)

        if not isinstance(data, dict):
            continue

        symbols = data.get("symbols")

        if isinstance(symbols, list) and symbols:
            print(
                f"Exchange info OK: "
                f"{len(symbols)} raw symbols"
            )
            return data

    return None


# ============================================================
# MARKET NORMALIZATION
# ============================================================

def normalize_symbol(symbol):

    symbol = str(symbol).upper().strip()

    symbol = symbol.replace("_", "")
    symbol = symbol.replace("-", "")
    symbol = symbol.replace("/", "")

    return symbol


# ============================================================
# GET MARKETS
# ============================================================

def get_markets():

    data = get_exchange_info()

    if not data:
        return []

    result = []

    for item in data.get("symbols", []):

        if not isinstance(item, dict):
            continue

        raw_symbol = item.get(
            "symbol",
            item.get("pair", "")
        )

        symbol = normalize_symbol(raw_symbol)

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        quote_asset = str(
            item.get(
                "quoteAsset",
                item.get(
                    "quote",
                    "USDT"
                )
            )
        ).upper()

        if not symbol:
            continue

        if status and status not in (
            "TRADING",
            "ACTIVE",
            "ENABLED",
        ):
            continue

        if quote_asset and quote_asset != "USDT":
            continue

        if not symbol.endswith("USDT"):
            continue

        if symbol not in result:
            result.append(symbol)

    return result[:MAX_MARKETS]


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol):

    normalized = normalize_symbol(symbol)

    candidates = [
        normalized,
        normalized.replace(
            "USDT",
            "_USDT"
        ),
    ]

    paths = [
        "/r/fapi/v1/klines",
        "/fapi/v1/klines",
    ]

    for path in paths:

        for candidate in candidates:

            params = {
                "symbol": candidate,
                "interval": INTERVAL,
                "limit": KLINE_LIMIT,
            }

            try:

                response = session.get(
                    BASE_URL + path,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                if response.status_code != 200:
                    continue

                data = response.json()

                if not isinstance(data, list):
                    continue

                if len(data) < 40:
                    continue

                valid = []

                for candle in data:

                    if not isinstance(candle, list):
                        continue

                    if len(candle) < 6:
                        continue

                    close_price = safe_float(
                        candle[4]
                    )

                    close_time = safe_float(
                        candle[6]
                    )

                    if close_price <= 0:
                        continue

                    if close_time <= 0:
                        continue

                    valid.append(candle)

                if len(valid) >= 40:
                    return valid

            except Exception:
                continue

    return []


# ============================================================
# CLOSED CANDLES
# ============================================================

def get_closed_closes(klines):

    if not isinstance(klines, list):
        return []

    if len(klines) < 2:
        return []

    current_time_ms = int(
        time.time() * 1000
    )

    closes = []

    for candle in klines:

        if not isinstance(candle, list):
            continue

        if len(candle) < 7:
            continue

        close_price = safe_float(
            candle[4]
        )

        close_time = safe_float(
            candle[6]
        )

        if close_price <= 0:
            continue

        if close_time <= 0:
            continue

        # فقط کندل‌هایی که زمان بسته‌شدنشان
        # از زمان فعلی گذشته است، بسته محسوب می‌شوند.
        if close_time <= current_time_ms:
            closes.append(close_price)

    return closes


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if not isinstance(values, list):
        return []

    if period <= 0:
        return []

    if len(values) < period:
        return []

    multiplier = 2.0 / (
        period + 1.0
    )

    first_average = (
        sum(values[:period]) / period
    )

    result = [first_average]

    previous = first_average

    for price in values[period:]:

        current = (
            (price - previous)
            * multiplier
        ) + previous

        result.append(current)

        previous = current

    return result


# ============================================================
# MACD
# ============================================================

def calculate_macd(closes):

    if not isinstance(closes, list):
        return None

    minimum = (
        SLOW_PERIOD
        + SIGNAL_PERIOD
        + 5
    )

    if len(closes) < minimum:
        return None

    fast = ema(
        closes,
        FAST_PERIOD
    )

    slow = ema(
        closes,
        SLOW_PERIOD
    )

    if not fast or not slow:
        return None

    # EMA سریع نسبت به EMA کند جلوتر است.
    offset = SLOW_PERIOD - FAST_PERIOD

    if offset < 0:
        return None

    if len(fast) <= offset:
        return None

    aligned_fast = fast[offset:]

    length = min(
        len(aligned_fast),
        len(slow)
    )

    if length < SIGNAL_PERIOD + 2:
        return None

    aligned_fast = aligned_fast[-length:]
    slow = slow[-length:]

    macd_values = []

    for fast_value, slow_value in zip(
        aligned_fast,
        slow
    ):
        macd_values.append(
            fast_value - slow_value
        )

    if len(macd_values) < SIGNAL_PERIOD + 2:
        return None

    signal_values = ema(
        macd_values,
        SIGNAL_PERIOD
    )

    if len(signal_values) < 2:
        return None

    signal_offset = (
        SIGNAL_PERIOD - 1
    )

    if len(macd_values) <= signal_offset:
        return None

    macd_for_signal = (
        macd_values[signal_offset:]
    )

    length = min(
        len(macd_for_signal),
        len(signal_values)
    )

    if length < 2:
        return None

    macd_for_signal = (
        macd_for_signal[-length:]
    )

    signal_values = (
        signal_values[-length:]
    )

    previous_macd = (
        macd_for_signal[-2]
    )

    previous_signal = (
        signal_values[-2]
    )

    current_macd = (
        macd_for_signal[-1]
    )

    current_signal = (
        signal_values[-1]
    )

    return {
        "macd": current_macd,
        "signal": current_signal,
        "previous_macd": previous_macd,
        "previous_signal": previous_signal,
    }


# ============================================================
# SIGNAL
# ============================================================

def get_signal(macd):

    if not macd:
        return None

    previous_macd = safe_float(
        macd.get("previous_macd")
    )

    previous_signal = safe_float(
        macd.get("previous_signal")
    )

    current_macd = safe_float(
        macd.get("macd")
    )

    current_signal = safe_float(
        macd.get("signal")
    )

    bullish_cross = (
        previous_macd <= previous_signal
        and current_macd > current_signal
    )

    bearish_cross = (
        previous_macd >= previous_signal
        and current_macd < current_signal
    )

    if bullish_cross:
        return "BUY"

    if bearish_cross:
        return "SELL"

    return None


# ============================================================
# PAPER ORDER
# ============================================================

def paper_order(
    symbol,
    side,
    price
):

    price = safe_float(price)

    if price <= 0:
        return None

    if side == "BUY":

        tp = price * (
            1.0 + TP_PCT
        )

        sl = price * (
            1.0 - SL_PCT
        )

    elif side == "SELL":

        tp = price * (
            1.0 - TP_PCT
        )

        sl = price * (
            1.0 + SL_PCT
        )

    else:
        return None

    return {
        "symbol": symbol,
        "side": side,
        "entry": price,
        "tp": tp,
        "sl": sl,
        "leverage": LEVERAGE,
        "margin": MARGIN_USDT,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    checked = 0
    macd_ready = 0
    buy_signals = 0
    sell_signals = 0
    errors = 0
    no_data = 0

    signals = []

    print("")
    print("================================")
    print("🤖 ATI FUTURES BOT V5")
    print("================================")
    print("Mode: PAPER")
    print("Exchange: Tabdeal Futures")
    print("MACD: 12/26/9")
    print("Timeframe: 5m")
    print("Real orders: DISABLED")
    print("================================")
    print("")

    markets = get_markets()

    if not markets:

        message = (
            "🤖 ATI FUTURES V5\n\n"
            "🟢 PAPER MODE\n"
            "Exchange: Tabdeal Futures\n\n"
            "❌ No Futures markets found.\n"
            f"Time: {now_utc()}"
        )

        print(message)
        send_telegram(message)
        return

    print(
        f"Markets loaded: {len(markets)}"
    )
    print("")

    for symbol in markets:

        checked += 1

        try:

            klines = get_klines(symbol)

            if not klines:

                no_data += 1

                print(
                    f"{symbol}: "
                    "NO KLINE DATA"
                )

                continue

            closes = get_closed_closes(
                klines
            )

            if len(closes) < 40:

                no_data += 1

                print(
                    f"{symbol}: "
                    f"closed candles={len(closes)}"
                )

                continue

            macd = calculate_macd(
                closes
            )

            if not macd:

                print(
                    f"{symbol}: "
                    "MACD not ready"
                )

                continue

            macd_ready += 1

            signal = get_signal(
                macd
            )

            if signal == "BUY":

                buy_signals += 1

                price = closes[-1]

                order = paper_order(
                    symbol,
                    "BUY",
                    price
                )

                if order:

                    signals.append({
                        "side": "BUY",
                        "symbol": symbol,
                        "entry": order["entry"],
                        "tp": order["tp"],
                        "sl": order["sl"],
                    })

                    print(
                        f"🟢 BUY {symbol} "
                        f"{price:.8f}"
                    )

            elif signal == "SELL":

                sell_signals += 1

                price = closes[-1]

                order = paper_order(
                    symbol,
                    "SELL",
                    price
                )

                if order:

                    signals.append({
                        "side": "SELL",
                        "symbol": symbol,
                        "entry": order["entry"],
                        "tp": order["tp"],
                        "sl": order["sl"],
                    })

                    print(
                        f"🔴 SELL {symbol} "
                        f"{price:.8f}"
                    )

        except Exception as exc:

            errors += 1

            print(
                f"{symbol}: ERROR "
                f"{str(exc)[:150]}"
            )

    runtime = (
        time.time() - started
    )

    print("")
    print("================================")
    print("ATI FUTURES RESULT")
    print("================================")
    print(
        f"Markets: {len(markets)}"
    )
    print(
        f"Checked: {checked}"
    )
    print(
        f"MACD ready: {macd_ready}"
    )
    print(
        f"BUY signals: {buy_signals}"
    )
    print(
        f"SELL signals: {sell_signals}"
    )
    print(
        f"No candle data: {no_data}"
    )
    print(
        f"Errors: {errors}"
    )
    print(
        f"Runtime: {runtime:.1f}s"
    )
    print(
        f"Time: {now_utc()}"
    )
    print("================================")

    # ========================================================
    # TELEGRAM
    # ========================================================

    if signals:

        lines = [
            "🤖 ATI FUTURES V5",
            "",
            "🟢 PAPER MODE",
            "Exchange: Tabdeal Futures",
            "MACD: 12/26/9",
            "Timeframe: 5m",
            "",
        ]

        for item in signals[:10]:

            side_icon = (
                "🟢"
                if item["side"] == "BUY"
                else "🔴"
            )

            lines.append(
                f"{side_icon} "
                f"{item['side']} "
                f"{item['symbol']}"
            )

            lines.append(
                f"Entry: "
                f"{item['entry']:.8f}"
            )

            lines.append(
                f"TP: "
                f"{item['tp']:.8f}"
            )

            lines.append(
                f"SL: "
                f"{item['sl']:.8f}"
            )

            lines.append("")

        lines.extend([
            "--------------------------------",
            f"Markets: {len(markets)}",
            f"MACD ready: {macd_ready}",
            f"BUY: {buy_signals}",
            f"SELL: {sell_signals}",
            f"Errors: {errors}",
            f"Runtime: {runtime:.1f}s",
            f"Time: {now_utc()}",
        ])

        message = "\n".join(lines)

    else:

        message = (
            "🤖 ATI FUTURES V5\n\n"
            "🟢 PAPER MODE\n"
            "Exchange: Tabdeal Futures\n"
            "MACD: 12/26/9\n"
            "Timeframe: 5m\n"
            "Real orders: DISABLED\n\n"
            f"Markets: {len(markets)}\n"
            f"Checked: {checked}\n"
            f"MACD ready: {macd_ready}\n"
            f"BUY signals: {buy_signals}\n"
            f"SELL signals: {sell_signals}\n"
            f"No candle data: {no_data}\n"
            f"Errors: {errors}\n"
            f"Runtime: {runtime:.1f}s\n"
            f"Time: {now_utc()}\n\n"
            "⚪ No new MACD crossover signal."
        )

    print("")
    print(message)
    print("")

    telegram_ok = send_telegram(
        message
    )

    print(
        "Telegram: "
        + ("OK" if telegram_ok else "FAILED")
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()

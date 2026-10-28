import os
import time
import requests
from datetime import datetime, timezone


# ============================================================
# ATI FUTURES BOT V6
# Tabdeal Futures | PAPER | MACD 12/26/9 | 5m
# No Tabdeal SDK required
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
    "User-Agent": "ATI-Futures-Bot/6.0",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured.")
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

    except requests.RequestException as exc:
        print(
            f"Telegram error: {str(exc)[:200]}"
        )

    return False


# ============================================================
# HTTP GET
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

        except ValueError:
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
                f"{len(symbols)} symbols"
            )
            return data

    print("Exchange info unavailable.")
    return None


# ============================================================
# NORMALIZE SYMBOL
# ============================================================

def normalize_symbol(symbol):

    symbol = str(symbol).upper().strip()

    for char in ("_", "-", "/"):
        symbol = symbol.replace(char, "")

    return symbol


# ============================================================
# MARKETS
# ============================================================

def get_markets():

    data = get_exchange_info()

    if not data:
        return []

    markets = []

    for item in data.get("symbols", []):

        if not isinstance(item, dict):
            continue

        raw_symbol = item.get(
            "symbol",
            item.get("pair", "")
        )

        symbol = normalize_symbol(raw_symbol)

        if not symbol:
            continue

        status = str(
            item.get("status", "TRADING")
        ).upper()

        quote = str(
            item.get(
                "quoteAsset",
                item.get("quote", "USDT")
            )
        ).upper()

        if status not in (
            "TRADING",
            "ACTIVE",
            "ENABLED",
        ):
            continue

        if quote != "USDT":
            continue

        if not symbol.endswith("USDT"):
            continue

        if symbol not in markets:
            markets.append(symbol)

    return markets[:MAX_MARKETS]


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol):

    normalized = normalize_symbol(symbol)

    candidates = [
        normalized,
        normalized.replace("USDT", "_USDT"),
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

        # Closed candle only
        if close_time <= current_time_ms:
            closes.append(close_price)

    return closes


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if not values:
        return []

    if period <= 0:
        return []

    if len(values) < period:
        return []

    multiplier = 2.0 / (
        period + 1.0
    )

    initial = sum(
        values[:period]
    ) / period

    result = [initial]

    previous = initial

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

    minimum = (
        SLOW_PERIOD
        + SIGNAL_PERIOD
        + 5
    )

    if len(closes) < minimum:
        return None

    fast_ema = ema(
        closes,
        FAST_PERIOD
    )

    slow_ema = ema(
        closes,
        SLOW_PERIOD
    )

    if not fast_ema or not slow_ema:
        return None

    offset = (
        SLOW_PERIOD
        - FAST_PERIOD
    )

    if len(fast_ema) <= offset:
        return None

    fast_aligned = fast_ema[offset:]

    length = min(
        len(fast_aligned),
        len(slow_ema)
    )

    if length < SIGNAL_PERIOD + 2:
        return None

    fast_aligned = fast_aligned[-length:]
    slow_aligned = slow_ema[-length:]

    macd_values = []

    for fast_value, slow_value in zip(
        fast_aligned,
        slow_aligned
    ):
        macd_values.append(
            fast_value - slow_value
        )

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

    macd_aligned = (
        macd_values[signal_offset:]
    )

    length = min(
        len(macd_aligned),
        len(signal_values)
    )

    if length < 2:
        return None

    macd_aligned = macd_aligned[-length:]
    signal_values = signal_values[-length:]

    return {
        "previous_macd": macd_aligned[-2],
        "previous_signal": signal_values[-2],
        "macd": macd_aligned[-1],
        "signal": signal_values[-1],
    }


# ============================================================
# SIGNAL
# ============================================================

def get_signal(macd):

    if not macd:
        return None

    previous_macd = safe_float(
        macd["previous_macd"]
    )

    previous_signal = safe_float(
        macd["previous_signal"]
    )

    current_macd = safe_float(
        macd["macd"]
    )

    current_signal = safe_float(
        macd["signal"]
    )

    if (
        previous_macd <= previous_signal
        and current_macd > current_signal
    ):
        return "BUY"

    if (
        previous_macd >= previous_signal
        and current_macd < current_signal
    ):
        return "SELL"

    return None


# ============================================================
# PAPER ORDER
# ============================================================

def create_paper_order(
    symbol,
    side,
    entry
):

    entry = safe_float(entry)

    if entry <= 0:
        return None

    if side == "BUY":

        tp = entry * (
            1.0 + TP_PCT
        )

        sl = entry * (
            1.0 - SL_PCT
        )

    elif side == "SELL":

        tp = entry * (
            1.0 - TP_PCT
        )

        sl = entry * (
            1.0 + SL_PCT
        )

    else:
        return None

    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
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
    no_data = 0
    errors = 0

    signals = []

    print("")
    print("======================================")
    print("🤖 ATI FUTURES BOT V6")
    print("======================================")
    print("Mode: PAPER")
    print("Exchange: Tabdeal Futures")
    print("MACD: 12/26/9")
    print("Timeframe: 5m")
    print("Real orders: DISABLED")
    print("======================================")
    print("")

    markets = get_markets()

    if not markets:

        message = (
            "🤖 ATI FUTURES V6\n\n"
            "🟢 PAPER MODE\n"
            "Exchange: Tabdeal Futures\n\n"
            "❌ No Futures markets found.\n\n"
            f"Time: {now_utc()}"
        )

        print(message)
        send_telegram(message)
        return

    print(
        f"Markets loaded: {len(markets)}"
    )

    for symbol in markets:

        checked += 1

        try:

            klines = get_klines(symbol)

            if not klines:

                no_data += 1

                print(
                    f"{symbol}: NO KLINE DATA"
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
                    "MACD NOT READY"
                )

                continue

            macd_ready += 1

            signal = get_signal(macd)

            if signal not in (
                "BUY",
                "SELL",
            ):
                continue

            price = closes[-1]

            order = create_paper_order(
                symbol,
                signal,
                price
            )

            if not order:
                continue

            if signal == "BUY":
                buy_signals += 1
                icon = "🟢"

            else:
                sell_signals += 1
                icon = "🔴"

            signals.append(order)

            print(
                f"{icon} {signal} "
                f"{symbol} "
                f"Entry={price:.8f} "
                f"TP={order['tp']:.8f} "
                f"SL={order['sl']:.8f}"
            )

        except Exception as exc:

            errors += 1

            print(
                f"{symbol}: ERROR "
                f"{str(exc)[:150]}"
            )

    runtime = time.time() - started

    print("")
    print("======================================")
    print("ATI FUTURES RESULT")
    print("======================================")
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
    print("======================================")

    # ========================================================
    # TELEGRAM MESSAGE
    # ========================================================

    lines = [
        "🤖 ATI FUTURES V6",
        "",
        "🟢 PAPER MODE",
        "Exchange: Tabdeal Futures",
        "MACD: 12/26/9",
        "Timeframe: 5m",
        "Real orders: DISABLED",
        "",
    ]

    if signals:

        for order in signals[:10]:

            icon = (
                "🟢"
                if order["side"] == "BUY"
                else "🔴"
            )

            lines.append(
                f"{icon} {order['side']} "
                f"{order['symbol']}"
            )

            lines.append(
                f"Entry: {order['entry']:.8f}"
            )

            lines.append(
                f"TP: {order['tp']:.8f}"
            )

            lines.append(
                f"SL: {order['sl']:.8f}"
            )

            lines.append("")

    else:

        lines.append(
            "⚪ No new MACD crossover signal."
        )

        lines.append("")

    lines.extend([
        "--------------------------------",
        f"Markets: {len(markets)}",
        f"Checked: {checked}",
        f"MACD ready: {macd_ready}",
        f"BUY: {buy_signals}",
        f"SELL: {sell_signals}",
        f"No data: {no_data}",
        f"Errors: {errors}",
        f"Runtime: {runtime:.1f}s",
        f"Time: {now_utc()}",
    ])

    message = "\n".join(lines)

    print("")
    print(message)
    print("")

    telegram_ok = send_telegram(message)

    print(
        "Telegram: "
        + (
            "OK"
            if telegram_ok
            else "FAILED"
        )
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()

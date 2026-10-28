
import os
import time
import requests
from datetime import datetime, timezone

# ATI FUTURES BOT V7 - DIAGNOSTIC PAPER MODE

BASE_URLS = [
    "https://api1.tabdeal.org",
    "https://api.tabdeal.org",
]

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

INTERVAL = "5m"
MAX_MARKETS = 30
KLINE_LIMIT = 200
TIMEOUT = 12

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
    "User-Agent": "ATI-Futures-Bot/7.0",
    "Accept": "application/json",
})


def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing")
        return False

    try:
        r = session.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4000],
            },
            timeout=TIMEOUT,
        )
        print("Telegram:", r.status_code, r.text[:200])
        return r.ok
    except requests.RequestException as exc:
        print("Telegram error:", str(exc)[:200])
        return False


def get_json(base, path, params=None):
    try:
        r = session.get(
            base + path,
            params=params or {},
            timeout=TIMEOUT,
        )
        preview = r.text[:180].replace("\n", " ")
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {preview}"

        try:
            return r.json(), "OK"
        except ValueError:
            return None, f"INVALID JSON: {preview}"

    except requests.RequestException as exc:
        return None, f"REQUEST ERROR: {str(exc)[:120]}"


def get_markets():
    paths = [
        "/r/fapi/v1/exchangeInfo",
        "/fapi/v1/exchangeInfo",
    ]

    for base in BASE_URLS:
        for path in paths:
            data, status = get_json(base, path)
            print("EXCHANGE INFO", base + path, status)

            if not isinstance(data, dict):
                continue

            symbols = data.get("symbols")
            if not isinstance(symbols, list):
                continue

            markets = []
            for item in symbols:
                if not isinstance(item, dict):
                    continue

                raw = str(
                    item.get("symbol", item.get("pair", ""))
                ).upper()

                symbol = raw.replace("_", "").replace("-", "")
                quote = str(
                    item.get("quoteAsset", item.get("quote", "USDT"))
                ).upper()
                status = str(item.get("status", "TRADING")).upper()

                if (
                    symbol.endswith("USDT")
                    and quote == "USDT"
                    and status in ("TRADING", "ACTIVE", "ENABLED")
                    and symbol not in markets
                ):
                    markets.append(symbol)

            if markets:
                print("MARKETS FOUND:", len(markets))
                return markets[:MAX_MARKETS]

    return []


def get_klines(symbol):
    # Test both symbol formats and likely API paths.
    symbols = [
        symbol,
        symbol.replace("USDT", "_USDT"),
    ]

    paths = [
        "/r/fapi/v1/klines",
        "/fapi/v1/klines",
        "/r/fapi/v1/continuousKlines",
        "/fapi/v1/continuousKlines",
    ]

    diagnostics = []

    for base in BASE_URLS:
        for path in paths:
            for candidate in symbols:
                params = {
                    "symbol": candidate,
                    "interval": INTERVAL,
                    "limit": KLINE_LIMIT,
                }

                # continuousKlines can require pair and contractType.
                if "continuousKlines" in path:
                    params = {
                        "pair": candidate,
                        "contractType": "PERPETUAL",
                        "interval": INTERVAL,
                        "limit": KLINE_LIMIT,
                    }

                data, status = get_json(base, path, params)

                if isinstance(data, list) and len(data) >= 40:
                    valid = []
                    for candle in data:
                        if not isinstance(candle, list) or len(candle) < 7:
                            continue
                        close = safe_float(candle[4])
                        close_time = safe_float(candle[6])
                        if close > 0 and close_time > 0:
                            valid.append(candle)

                    if len(valid) >= 40:
                        print(
                            "KLINES OK:", symbol, base + path,
                            "symbol=", candidate, "candles=", len(valid)
                        )
                        return valid

                    status = f"LIST BUT INVALID/SHORT: {len(valid)}"

                diagnostics.append(
                    f"{base}{path} [{candidate}]: {status}"
                )

    print("KLINE DIAGNOSTICS", symbol)
    for line in diagnostics[:8]:
        print(" ", line)

    return []


def closed_closes(klines):
    now_ms = int(time.time() * 1000)
    result = []

    for candle in klines:
        if len(candle) < 7:
            continue

        close = safe_float(candle[4])
        close_time = safe_float(candle[6])

        if close > 0 and 0 < close_time < now_ms:
            result.append(close)

    return result


def ema(values, period):
    if len(values) < period:
        return []

    alpha = 2.0 / (period + 1)
    average = sum(values[:period]) / period
    output = [average]

    for value in values[period:]:
        average = alpha * value + (1 - alpha) * average
        output.append(average)

    return output


def calculate_macd(closes):
    fast = ema(closes, FAST_PERIOD)
    slow = ema(closes, SLOW_PERIOD)

    if not fast or not slow:
        return None

    offset = SLOW_PERIOD - FAST_PERIOD
    fast = fast[offset:]
    n = min(len(fast), len(slow))
    fast, slow = fast[-n:], slow[-n:]

    macd_line = [a - b for a, b in zip(fast, slow)]
    signal_line = ema(macd_line, SIGNAL_PERIOD)

    if len(signal_line) < 2:
        return None

    macd_line = macd_line[SIGNAL_PERIOD - 1:]
    n = min(len(macd_line), len(signal_line))
    macd_line = macd_line[-n:]
    signal_line = signal_line[-n:]

    return {
        "pm": macd_line[-2],
        "ps": signal_line[-2],
        "m": macd_line[-1],
        "s": signal_line[-1],
    }


def get_signal(m):
    if not m:
        return None

    if m["pm"] <= m["ps"] and m["m"] > m["s"]:
        return "BUY"

    if m["pm"] >= m["ps"] and m["m"] < m["s"]:
        return "SELL"

    return None


def make_paper_order(symbol, side, entry):
    if entry <= 0:
        return None

    if side == "BUY":
        tp = entry * (1 + TP_PCT)
        sl = entry * (1 - SL_PCT)
    else:
        tp = entry * (1 - TP_PCT)
        sl = entry * (1 + SL_PCT)

    return {
        "symbol": symbol,
        "side": side,
        "entry": entry,
        "tp": tp,
        "sl": sl,
    }


def main():
    started = time.time()
    ready = buys = sells = no_data = errors = 0
    signals = []

    print("\nATI FUTURES V7 - PAPER MODE")
    print("Real trading disabled:", not REAL_TRADING)

    markets = get_markets()
    print("Markets:", len(markets))

    if not markets:
        message = (
            "ATI FUTURES V7\n"
            "No futures markets found.\n"
            f"Time: {now_utc()}"
        )
        print(message)
        send_telegram(message)
        return

    for symbol in markets:
        try:
            klines = get_klines(symbol)

            if not klines:
                no_data += 1
                continue

            closes = closed_closes(klines)
            if len(closes) < 40:
                no_data += 1
                print(symbol, "closed candles:", len(closes))
                continue

            macd = calculate_macd(closes)
            if not macd:
                print(symbol, "MACD insufficient data")
                continue

            ready += 1
            side = get_signal(macd)

            if side:
                order = make_paper_order(symbol, side, closes[-1])
                if order:
                    signals.append(order)
                    if side == "BUY":
                        buys += 1
                    else:
                        sells += 1

                    print(
                        side, symbol,
                        "entry=", order["entry"],
                        "TP=", order["tp"],
                        "SL=", order["sl"],
                    )

        except Exception as exc:
            errors += 1
            print(symbol, "ERROR:", str(exc)[:180])

    runtime = time.time() - started

    lines = [
        "🤖 ATI FUTURES V7",
        "",
        "🟢 PAPER MODE",
        "Exchange: Tabdeal Futures",
        "MACD: 12/26/9 | 5m",
        "Real orders: DISABLED",
        "",
    ]

    for order in signals[:10]:
        lines.extend([
            f"{order['side']} {order['symbol']}",
            f"Entry: {order['entry']:.8f}",
            f"TP: {order['tp']:.8f}",
            f"SL: {order['sl']:.8f}",
            "",
        ])

    if not signals:
        lines.extend([
            "No new MACD crossover signal.",
            "",
        ])

    lines.extend([
        "--------------------------------",
        f"Markets: {len(markets)}",
        f"Checked: {len(markets)}",
        f"MACD ready: {ready}",
        f"BUY: {buys}",
        f"SELL: {sells}",
        f"No data: {no_data}",
        f"Errors: {errors}",
        f"Runtime: {runtime:.1f}s",
        f"Time: {now_utc()}",
    ])

    message = "\n".join(lines)
    print("\n" + message)
    send_telegram(message)


if __name__ == "__main__":
    main()

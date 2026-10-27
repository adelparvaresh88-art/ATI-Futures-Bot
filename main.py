import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# ATI FUTURES V4
# Tabdeal Futures | PAPER | MACD 12/26/9 | 5m
# Telegram Diagnostic + Heartbeat
#
# REAL TRADING: DISABLED
# ============================================================

# ============================================================
# CONFIG
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

BASE_URLS = [
    "https://api1.tabdeal.org",
    "https://api.tabdeal.org",
]

EXCHANGE_INFO_PATHS = [
    "/r/fapi/v1/exchangeInfo",
    "/fapi/v1/exchangeInfo",
]

KLINE_PATHS = [
    "/r/fapi/v1/klines",
    "/fapi/v1/klines",
]

INTERVAL = "5m"

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

MAX_MARKETS = 30
KLINE_LIMIT = 100

REQUEST_TIMEOUT = 12
TELEGRAM_TIMEOUT = 20
REQUEST_DELAY = 0.10

PAPER_MODE = True
REAL_TRADING = False

LEVERAGE = 3
MARGIN_USDT = 2.0


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_configured():
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def telegram_api(method, payload=None):
    if not TELEGRAM_TOKEN:
        print("Telegram: BOT TOKEN MISSING")
        return None

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/"
        f"{method}"
    )

    try:
        response = requests.post(
            url,
            json=payload or {},
            timeout=TELEGRAM_TIMEOUT,
        )

        print(
            f"Telegram API {method}: "
            f"HTTP {response.status_code}"
        )

        try:
            data = response.json()
        except Exception:
            data = {
                "ok": False,
                "description": response.text[:500],
            }

        if not data.get("ok", False):
            print(
                "Telegram API ERROR:",
                data.get("description", "unknown error"),
            )

        return data

    except Exception as exc:
        print(
            f"Telegram exception ({method}):",
            repr(exc),
        )
        return None


def telegram_test():
    print()
    print("=" * 64)
    print("TELEGRAM DIAGNOSTIC")
    print("=" * 64)

    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        print("=" * 64)
        return False

    if not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID is missing")
        print("=" * 64)
        return False

    print(
        "BOT TOKEN: configured "
        f"(length={len(TELEGRAM_TOKEN)})"
    )

    print(
        "CHAT ID: configured "
        f"(length={len(TELEGRAM_CHAT_ID)})"
    )

    result = telegram_api("getMe")

    if not result or not result.get("ok"):
        print("ERROR: Telegram bot authentication FAILED")
        print("=" * 64)
        return False

    bot = result.get("result", {})

    print("Telegram bot connected")
    print(
        "Username:",
        bot.get("username", "-"),
    )
    print(
        "Name:",
        bot.get("first_name", "-"),
    )

    print("=" * 64)

    return True


def telegram(message):
    if not TELEGRAM_TOKEN:
        print("Telegram: BOT TOKEN MISSING")
        return False

    if not TELEGRAM_CHAT_ID:
        print("Telegram: CHAT ID MISSING")
        return False

    if not message:
        print("Telegram: EMPTY MESSAGE")
        return False

    max_length = 3900
    chunks = []

    while len(message) > max_length:
        split_at = message.rfind(
            "\n",
            0,
            max_length,
        )

        if split_at <= 0:
            split_at = max_length

        chunks.append(message[:split_at])
        message = message[split_at:]

    if message:
        chunks.append(message)

    success = True

    for index, chunk in enumerate(chunks, 1):
        print(
            f"Telegram: sending "
            f"{index}/{len(chunks)}"
        )

        result = telegram_api(
            "sendMessage",
            {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            },
        )

        if not result or not result.get("ok"):
            success = False

            description = "unknown error"

            if result:
                description = result.get(
                    "description",
                    "unknown error",
                )

            print(
                "Telegram SEND ERROR:",
                description,
            )

        else:
            print(
                f"Telegram message "
                f"{index}/{len(chunks)} sent"
            )

    return success


# ============================================================
# HTTP
# ============================================================

def http_get(base_url, path, params=None):
    url = base_url.rstrip("/") + path

    response = requests.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "ATI-FUTURES-V4",
            "Accept": "application/json",
        },
    )

    print(
        f"GET {url} "
        f"-> {response.status_code}"
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Invalid JSON response: {exc}"
        )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():
    errors = []

    for base_url in BASE_URLS:
        for path in EXCHANGE_INFO_PATHS:
            try:
                data = http_get(
                    base_url,
                    path,
                )

                if (
                    isinstance(data, dict)
                    and isinstance(
                        data.get("symbols"),
                        list,
                    )
                ):
                    print(
                        "ExchangeInfo OK:",
                        base_url + path,
                    )

                    return data

                errors.append(
                    f"{base_url}{path}: "
                    "invalid exchangeInfo"
                )

            except Exception as exc:
                errors.append(
                    f"{base_url}{path}: {exc}"
                )

    raise RuntimeError(
        "All exchangeInfo endpoints failed:\n"
        + "\n".join(errors)
    )


# ============================================================
# SYMBOL
# ============================================================

def normalize_symbol(symbol):
    symbol = str(symbol or "").upper()

    symbol = symbol.replace("_", "")
    symbol = symbol.replace("-", "")
    symbol = symbol.replace("/", "")

    return symbol


# ============================================================
# MARKETS
# ============================================================

def get_markets():
    data = get_exchange_info()

    raw_symbols = data.get(
        "symbols",
        [],
    )

    markets = []

    for item in raw_symbols:
        if not isinstance(item, dict):
            continue

        raw_symbol = item.get(
            "symbol",
            "",
        )

        symbol = normalize_symbol(
            raw_symbol
        )

        status = str(
            item.get(
                "status",
                "",
            )
        ).upper()

        quote = str(
            item.get(
                "quoteAsset",
                "",
            )
        ).upper()

        if not symbol:
            continue

        if quote and quote != "USDT":
            continue

        if not symbol.endswith("USDT"):
            continue

        if status and status != "TRADING":
            continue

        if symbol not in markets:
            markets.append(symbol)

    markets.sort()

    return markets[:MAX_MARKETS]


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol):
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": KLINE_LIMIT,
    }

    errors = []

    for base_url in BASE_URLS:
        for path in KLINE_PATHS:
            try:
                data = http_get(
                    base_url,
                    path,
                    params,
                )

                if (
                    isinstance(data, list)
                    and len(data) > 0
                ):
                    return data

                errors.append(
                    f"{base_url}{path}: "
                    "empty response"
                )

            except Exception as exc:
                errors.append(
                    f"{base_url}{path}: {exc}"
                )

    print(
        f"{symbol}: all kline endpoints failed"
    )

    for error in errors:
        print(
            "   ",
            error,
        )

    return []


# ============================================================
# CANDLES
# ============================================================

def candle_close(candle):
    if not isinstance(
        candle,
        (list, tuple),
    ):
        return None

    if len(candle) < 5:
        return None

    try:
        value = float(candle[4])
    except Exception:
        return None

    if value <= 0:
        return None

    return value


def extract_closed_closes(raw):
    if not isinstance(raw, list):
        return []

    closes = []

    for candle in raw:
        value = candle_close(candle)

        if value is not None:
            closes.append(value)

    # حذف آخرین کندل جاری
    if len(closes) >= 2:
        closes = closes[:-1]

    return closes


# ============================================================
# EMA
# ============================================================

def ema(values, period):
    if not values:
        return []

    if len(values) < period:
        return []

    multiplier = 2.0 / (period + 1)

    first = (
        sum(values[:period])
        / period
    )

    result = [first]

    previous = first

    for value in values[period:]:
        current = (
            (value - previous)
            * multiplier
            + previous
        )

        result.append(current)
        previous = current

    return result


# ============================================================
# MACD
# ============================================================

def calculate_macd(closes):
    minimum = (
        MACD_SLOW
        + MACD_SIGNAL
        + 5
    )

    if len(closes) < minimum:
        return None

    fast = ema(
        closes,
        MACD_FAST,
    )

    slow = ema(
        closes,
        MACD_SLOW,
    )

    if not fast or not slow:
        return None

    offset = MACD_SLOW - MACD_FAST

    if len(fast) <= offset:
        return None

    fast_aligned = fast[offset:]

    count = min(
        len(fast_aligned),
        len(slow),
    )

    if count < MACD_SIGNAL + 2:
        return None

    fast_aligned = fast_aligned[-count:]
    slow_aligned = slow[-count:]

    macd_line = []

    for fast_value, slow_value in zip(
        fast_aligned,
        slow_aligned,
    ):
        macd_line.append(
            fast_value - slow_value
        )

    signal_line = ema(
        macd_line,
        MACD_SIGNAL,
    )

    if len(signal_line) < 2:
        return None

    macd_for_signal = macd_line[
        -len(signal_line):
    ]

    if len(macd_for_signal) < 2:
        return None

    previous_macd = macd_for_signal[-2]
    current_macd = macd_for_signal[-1]

    previous_signal = signal_line[-2]
    current_signal = signal_line[-1]

    previous_histogram = (
        previous_macd
        - previous_signal
    )

    current_histogram = (
        current_macd
        - current_signal
    )

    return {
        "macd": current_macd,
        "signal": current_signal,
        "histogram": current_histogram,
        "previous_macd": previous_macd,
        "previous_signal": previous_signal,
        "previous_histogram": previous_histogram,
    }


# ============================================================
# SIGNAL
# ============================================================

def get_signal(macd):
    if not macd:
        return None

    previous_macd = macd[
        "previous_macd"
    ]

    previous_signal = macd[
        "previous_signal"
    ]

    current_macd = macd[
        "macd"
    ]

    current_signal = macd[
        "signal"
    ]

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
# FORMAT
# ============================================================

def fmt(value):
    if value is None:
        return "-"

    try:
        return f"{float(value):.8f}"
    except Exception:
        return str(value)


# ============================================================
# MAIN
# ============================================================

def run():
    start_time = time.time()

    buy_signals = []
    sell_signals = []

    errors = 0
    checked = 0
    macd_ready = 0

    print()
    print("=" * 64)
    print("ATI FUTURES V4")
    print("=" * 64)

    print("Mode: PAPER")
    print("Exchange: Tabdeal Futures")
    print("MACD: 12/26/9")
    print("Timeframe: 5m")
    print("Real orders: DISABLED")
    print("Time:", utc_now())
    print("=" * 64)

    # --------------------------------------------------------
    # Telegram test
    # --------------------------------------------------------

    telegram_ok = telegram_test()

    if telegram_ok:
        telegram(
            "🤖 ATI FUTURES V4\n\n"
            "🟢 PAPER MODE\n"
            "Exchange: Tabdeal Futures\n"
            "MACD: 12/26/9\n"
            "Timeframe: 5m\n"
            "Real orders: DISABLED\n\n"
            f"Time: {utc_now()}\n"
            "Telegram: CONNECTED"
        )
    else:
        print(
            "Telegram diagnostic failed."
        )

    # --------------------------------------------------------
    # Markets
    # --------------------------------------------------------

    try:
        markets = get_markets()
    except Exception as exc:
        errors += 1

        error_text = (
            "❌ Exchange error:\n"
            f"{exc}"
        )

        print(error_text)

        telegram(error_text)

        return

    print()
    print(
        f"Markets found: {len(markets)}"
    )

    if not markets:
        message = (
            "⚠️ ATI FUTURES\n\n"
            "No USDT futures markets found.\n"
            f"Time: {utc_now()}"
        )

        print(message)
        telegram(message)

        return

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    for symbol in markets:
        checked += 1

        print()
        print("-" * 60)
        print(
            f"[{checked}/{len(markets)}] "
            f"{symbol}"
        )

        try:
            raw_klines = get_klines(
                symbol
            )

            closes = extract_closed_closes(
                raw_klines
            )

            if len(closes) < (
                MACD_SLOW
                + MACD_SIGNAL
                + 5
            ):
                print(
                    f"{symbol}: "
                    f"insufficient candles "
                    f"({len(closes)})"
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

            print(
                f"{symbol}: "
                f"MACD={fmt(macd['macd'])} | "
                f"Signal={fmt(macd['signal'])} | "
                f"Hist={fmt(macd['histogram'])} | "
                f"Cross={signal or '-'}"
            )

            if signal == "BUY":
                buy_signals.append(
                    {
                        "symbol": symbol,
                        "macd": macd["macd"],
                        "signal": macd["signal"],
                        "histogram": macd["histogram"],
                    }
                )

            elif signal == "SELL":
                sell_signals.append(
                    {
                        "symbol": symbol,
                        "macd": macd["macd"],
                        "signal": macd["signal"],
                        "histogram": macd["histogram"],
                    }
                )

        except Exception as exc:
            errors += 1

            print(
                f"{symbol}: ERROR: {exc}"
            )

        time.sleep(
            REQUEST_DELAY
        )

    # --------------------------------------------------------
    # Runtime
    # --------------------------------------------------------

    runtime = time.time() - start_time

    # --------------------------------------------------------
    # Build report
    # --------------------------------------------------------

    lines = []

    lines.append(
        "🤖 ATI FUTURES V4"
    )
    lines.append("")
    lines.append(
        "Mode: 🟢 PAPER"
    )
    lines.append(
        "Exchange: Tabdeal Futures"
    )
    lines.append(
        "MACD: 12/26/9"
    )
    lines.append(
        "Timeframe: 5m"
    )
    lines.append(
        "Real orders: DISABLED"
    )
    lines.append("")
    lines.append(
        f"Markets: {len(markets)}"
    )
    lines.append(
        f"Checked: {checked}"
    )
    lines.append(
        f"MACD ready: {macd_ready}"
    )
    lines.append(
        f"BUY signals: {len(buy_signals)}"
    )
    lines.append(
        f"SELL signals: {len(sell_signals)}"
    )
    lines.append(
        f"Errors: {errors}"
    )
    lines.append(
        f"Runtime: {runtime:.1f}s"
    )
    lines.append(
        f"Time: {utc_now()}"
    )

    # --------------------------------------------------------
    # BUY signals
    # --------------------------------------------------------

    if buy_signals:
        lines.append("")
        lines.append("🟢 BUY SIGNALS")

        for item in buy_signals:
            lines.append(
                f"{item['symbol']} | "
                f"MACD {fmt(item['macd'])} | "
                f"Signal {fmt(item['signal'])} | "
                f"Hist {fmt(item['histogram'])}"
            )

    # --------------------------------------------------------
    # SELL signals
    # --------------------------------------------------------

    if sell_signals:
        lines.append("")
        lines.append("🔴 SELL SIGNALS")

        for item in sell_signals:
            lines.append(
                f"{item['symbol']} | "
                f"MACD {fmt(item['macd'])} | "
                f"Signal {fmt(item['signal'])} | "
                f"Hist {fmt(item['histogram'])}"
            )

    # --------------------------------------------------------
    # No signal
    # --------------------------------------------------------

    if not buy_signals and not sell_signals:
        lines.append("")
        lines.append(
            "⚪ No new MACD crossover signal."
        )

    report = "\n".join(lines)

    # --------------------------------------------------------
    # Console
    # --------------------------------------------------------

    print()
    print("=" * 64)
    print(report)
    print("=" * 64)

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    telegram(report)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        run()

    except KeyboardInterrupt:
        print(
            "Program interrupted."
        )

    except Exception as exc:
        print()
        print("=" * 64)
        print("FATAL ERROR")
        print("=" * 64)
        print(
            repr(exc)
        )

        telegram(
            "🚨 ATI FUTURES FATAL ERROR\n\n"
            f"{exc}\n\n"
            f"Time: {utc_now()}"
        )

        raise

import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# ATI FUTURES V3
# Tabdeal Futures | PAPER | MACD 12/26/9 | 5m
# Telegram diagnostics + heartbeat
#
# REAL TRADING: DISABLED
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")

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
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_configured():
    return bool(
        TELEGRAM_TOKEN
        and TELEGRAM_CHAT_ID
    )


def telegram_api(method, payload=None):
    if not TELEGRAM_TOKEN:
        print("Telegram: BOT TOKEN MISSING")
        return None

    url = (
        f"https://api.telegram.org/"
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

        if not response.ok:
            print(
                "Telegram HTTP ERROR:",
                response.text[:1000],
            )
            return data

        if not data.get("ok", False):
            print(
                "Telegram API ERROR:",
                data,
            )
            return data

        return data

    except Exception as exc:
        print(
            f"Telegram exception ({method}):",
            repr(exc),
        )
        return None


def telegram_test():
    """
    تست کامل Bot Token با getMe.
    """

    print()
    print("=" * 64)
    print("TELEGRAM DIAGNOSTIC")
    print("=" * 64)

    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is MISSING")
        print("=" * 64)
        return False

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID is MISSING")
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
        print("❌ Telegram bot authentication FAILED")
        print("=" * 64)
        return False

    bot = result.get("result", {})

    print(
        "✅ Telegram bot connected:"
    )

    print(
        "   username:",
        bot.get("username", "-"),
    )

    print(
        "   name:",
        bot.get("first_name", "-"),
    )

    print("=" * 64)

    return True


def telegram(message):
    """
    ارسال پیام به Telegram.
    """

    if not TELEGRAM_TOKEN:
        print(
            "Telegram: "
            "TELEGRAM_BOT_TOKEN MISSING"
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "Telegram: "
            "TELEGRAM_CHAT_ID MISSING"
        )
        return False

    if not message:
        print("Telegram: empty message")
        return False

    # Telegram حدود 4096 کاراکتر را قبول می‌کند.
    # برای جلوگیری از خطای طول پیام، خرد می‌کنیم.
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

        chunks.append(
            message[:split_at]
        )

        message = message[split_at:]

    if message:
        chunks.append(message)

    success = True

    for index, chunk in enumerate(chunks, 1):

        print(
            f"Telegram: sending "
            f"message {index}/{len(chunks)}..."
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

            print(
                "❌ Telegram send failed."
            )

            if result:
                print(
                    "Telegram description:",
                    result.get(
                        "description",
                        "unknown error",
                    ),
                )

        else:
            print(
                f"✅ Telegram message "
                f"{index}/{len(chunks)} sent."
            )

    return success


# ============================================================
# HTTP
# ============================================================

def http_get(
    base_url,
    path,
    params=None,
):

    url = (
        base_url.rstrip("/")
        + path
    )

    response = requests.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
        headers={
            "User-Agent": "ATI-FUTURES-V3",
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
            f"{response.text[:250]}"
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
                    f"invalid exchangeInfo"
                )

            except Exception as exc:

                errors.append(
                    f"{base_url}{path}: "
                    f"{exc}"
                )

    raise RuntimeError(
        "All exchangeInfo endpoints failed:\n"
        + "\n".join(errors)
    )


# ============================================================
# SYMBOL
# ============================================================

def normalize_symbol(symbol):

    symbol = str(
        symbol or ""
    ).upper()

    symbol = symbol.replace(
        "_",
        "",
    )

    symbol = symbol.replace(
        "-",
        "",
    )

    symbol = symbol.replace(
        "/",
        "",
    )

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

        if not isinstance(
            item,
            dict,
        ):
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

        if (
            status
            and status != "TRADING"
        ):
            continue

        if symbol not in markets:
            markets.append(symbol)

    markets.sort()

    return markets[:MAX_MARKETS]


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol):

    errors = []

    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": KLINE_LIMIT,
    }

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
                    f"empty response"
                )

            except Exception as exc:

                errors.append(
                    f"{base_url}{path}: "
                    f"{exc}"
                )

    print(
        f"{symbol}: "
        f"all kline endpoints failed"
    )

    for error in errors:
        print(
            "   ",
            error,
        )

    return []


# ============================================================
# CANDLE
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
        return float(candle[4])

    except Exception:
        return None


def extract_closed_closes(raw):

    if not isinstance(
        raw,
        list,
    ):
        return []

    closes = []

    for candle in raw:

        value = candle_close(
            candle
        )

        if value is None:
            continue

        if value <= 0:
            continue

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

    multiplier = 2.0 / (
        period + 1
    )

    first = (
        sum(values[:period])
        / period
    )

    result = [first]

    previous = first

    for value in values[period:]:

        current = (
            (
                value
                - previous
            )
            * multiplier
            + previous
        )

        result.append(
            current
        )

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

    offset = (
        MACD_SLOW
        - MACD_FAST
    )

    if len(fast) <= offset:
        return None

    fast_aligned = fast[offset:]

    count = min(
        len(fast_aligned),
        len(slow),
    )

    if count < MACD_SIGNAL + 2:
        return None

    fast_aligned = (
        fast_aligned[-count:]
    )

    slow_aligned = (
        slow[-count:]
    )

    macd_line = []

    for (
        fast_value,
        slow_value,
    ) in zip(
        fast_aligned,
        slow_aligned,
    ):

        macd_line.append(
            fast_value
            - slow_value
        )

    signal_line = ema(
        macd_line,
        MACD_SIGNAL,
    )

    if len(signal_line) < 2:
        return None

    macd_for_signal = (
        macd_line[
            -len(signal_line):
        ]
    )

    if len(macd_for_signal) < 2:
        return None

    previous_macd = (
        macd_for_signal[-2]
    )

    current_macd = (
        macd_for_signal[-1]
    )

    previous_signal = (
        signal_line[-2]
    )

    current_signal = (
        signal_line[-1]
    )

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
        previous_macd
        <= previous_signal
        and
        current_macd
        > current_signal
    )

    bearish_cross = (
        previous_macd
        >= previous_signal
        and
        current_macd
        < current_signal
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

    value = float(value)

    if abs(value) >= 1000:
        return f"{value:.2f}"

    if abs(value) >= 1:
        return f"{value:.6f}"

    if abs(value) >= 0.01:
        return f"{value:.8f}"

    return f"{value:.10f}"


# ============================================================
# MAIN
# ============================================================

def run():

    started = time.time()

    print()
    print("=" * 64)
    print("🤖 ATI FUTURES V3")
    print("=" * 64)
    print("Exchange : Tabdeal Futures")
    print("Mode     : PAPER")
    print("Real     : DISABLED")
    print("MACD     : 12/26/9")
    print("Timeframe: 5m")
    print("Markets  :", MAX_MARKETS)
    print("Leverage :", LEVERAGE)
    print("Margin   :", MARGIN_USDT, "USDT")
    print("=" * 64)

    # ========================================================
    # TELEGRAM TEST
    # ========================================================

    telegram_ok = telegram_test()

    if telegram_ok:

        startup_message = (
            "🤖 ATI FUTURES V3\n\n"
            "🟢 Bot started successfully\n"
            "🟢 Telegram connection: OK\n"
            "🟢 PAPER MODE\n"
            "🚫 REAL TRADING: DISABLED\n\n"
            "Exchange: Tabdeal Futures\n"
            "MACD: 12/26/9\n"
            "Timeframe: 5m\n\n"
            f"Time: {utc_now()}"
        )

        telegram(
            startup_message
        )

    else:

        print(
            "⚠️ Telegram is NOT working."
        )

    # ========================================================
    # CREDENTIALS
    # ========================================================

    if API_KEY:
        print(
            "TABDEAL_API_KEY: OK"
        )
    else:
        print(
            "TABDEAL_API_KEY: MISSING"
        )

    if API_SECRET:
        print(
            "TABDEAL_API_SECRET: OK"
        )
    else:
        print(
            "TABDEAL_API_SECRET: MISSING"
        )

    # ========================================================
    # EXCHANGE
    # ========================================================

    try:

        markets = get_markets()

    except Exception as exc:

        error_text = (
            "❌ ATI FUTURES V3\n\n"
            "ExchangeInfo FAILED\n\n"
            f"Error:\n{exc}\n\n"
            f"Time: {utc_now()}"
        )

        print(error_text)

        telegram(
            error_text
        )

        return

    if not markets:

        error_text = (
            "❌ ATI FUTURES V3\n\n"
            "No USDT Futures markets found.\n\n"
            f"Time: {utc_now()}"
        )

        print(error_text)

        telegram(
            error_text
        )

        return

    print()
    print(
        f"Markets discovered: "
        f"{len(markets)}"
    )

    print(
        "Markets:",
        ", ".join(markets),
    )

    # ========================================================
    # SCANNER
    # ========================================================

    checked = 0
    ready = 0
    errors = 0

    buy_signals = []
    sell_signals = []

    for symbol in markets:

        checked += 1

        try:

            raw = get_klines(
                symbol
            )

            if not raw:

                print(
                    f"{symbol}: "
                    "NO KLINE DATA"
                )

                continue

            closes = extract_closed_closes(
                raw
            )

            print(
                f"{symbol}: "
                f"raw={len(raw)} "
                f"closed={len(closes)}"
            )

            if len(closes) < 40:

                print(
                    f"{symbol}: "
                    f"insufficient candles "
                    f"({len(closes)})"
                )

                continue

            ready += 1

            macd = calculate_macd(
                closes
            )

            if not macd:

                print(
                    f"{symbol}: "
                    "MACD not ready"
                )

                continue

            signal = get_signal(
                macd
            )

            print(
                f"{symbol} | "
                f"MACD={fmt(macd['macd'])} | "
                f"Signal={fmt(macd['signal'])} | "
                f"Hist={fmt(macd['histogram'])} | "
                f"Cross={signal or '-'}"
            )

            if signal == "BUY":

                buy_signals.append({
                    "symbol": symbol,
                    "macd": macd["macd"],
                    "signal": macd["signal"],
                    "histogram": macd[
                        "histogram"
                    ],
                })

            elif signal == "SELL":

                sell_signals.append({
                    "symbol": symbol,
                    "macd": macd["macd"],
                    "signal": macd["signal"],
                    "histogram": macd[
                        "histogram"
                    ],
                )

        except Exception as exc:

            errors += 1

            print(
                f"{symbol}: ERROR: "
                f"{exc}"
            )

        time.sleep(
            REQUEST_DELAY
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    runtime = (
        time.time()
        - started
    )

    now = utc_now()

    print()
    print("=" * 64)
    print("SCAN COMPLETE")
    print("=" * 64)

    print(
        f"Markets      : {len(markets)}"
    )

    print(
        f"Checked      : {checked}"
    )

    print(
        f"MACD ready   : {ready}"
    )

    print(
        f"BUY signals  : {len(buy_signals)}"
    )

    print(
        f"SELL signals : {len(sell_signals)}"
    )

    print(
        f"Errors       : {errors}"
    )

    print(
        f"Runtime      : {runtime:.1f}s"
    )

    print(
        f"Time         : {now}"
    )

    print("=" * 64)

    # ========================================================
    # TELEGRAM REPORT
    # ========================================================

    text = (
        "🤖 ATI FUTURES V3\n\n"
        "🟢 PAPER MODE\n"
        "🚫 REAL TRADING: DISABLED\n\n"
        "Exchange: Tabdeal Futures\n"
        "MACD: 12/26/9\n"
        "Timeframe: 5m\n"
        "Leverage: 3x\n"
        "Margin: 2 USDT\n\n"
        f"Markets: {len(markets)}\n"
        f"Checked: {checked}\n"
        f"MACD ready: {ready}\n"
        f"BUY: {len(buy_signals)}\n"
        f"SELL: {len(sell_signals)}\n"
        f"Errors: {errors}\n"
        f"Runtime: {runtime:.1f}s\n\n"
    )

    if buy_signals:

        text += (
            "🟢 BUY SIGNALS\n\n"
        )

        for item in buy_signals[:5]:

            text += (
                f"📈 {item['symbol']}\n"
                f"MACD: "
                f"{fmt(item['macd'])}\n"
                f"Signal: "
                f"{fmt(item['signal'])}\n"
                f"Histogram: "
                f"{fmt(item['histogram'])}\n\n"
            )

    if sell_signals:

        text += (
            "🔴 SELL SIGNALS\n\n"
        )

        for item in sell_signals[:5]:

            text += (
                f"📉 {item['symbol']}\n"
                f"MACD: "
                f"{fmt(item['macd'])}\n"
                f"Signal: "
                f"{fmt(item['signal'])}\n"
                f"Histogram: "
                f"{fmt(item['histogram'])}\n\n"
            )

    if (
        not buy_signals
        and not sell_signals
    ):

        text += (
            "⚪ No new MACD cross\n"
            "on closed 5m candles.\n\n"
        )

    text += (
        f"Time: {now}"
    )

    telegram(
        text
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    run()

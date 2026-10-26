import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# ATI FUTURES V2
# Tabdeal Futures | PAPER | MACD 12/26/9 | 5m
#
# هدف:
# 1) دریافت بازارهای Futures
# 2) دریافت کندل‌های 5 دقیقه‌ای
# 3) حذف کندل جاری و استفاده فقط از کندل بسته‌شده
# 4) محاسبه MACD 12/26/9
# 5) تشخیص کراس BUY / SELL
# 6) ارسال گزارش به Telegram
#
# REAL TRADING: DISABLED
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ------------------------------------------------------------
# Tabdeal
# ------------------------------------------------------------

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

# ------------------------------------------------------------
# Strategy
# ------------------------------------------------------------

INTERVAL = "5m"

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

MAX_MARKETS = 30
KLINE_LIMIT = 100

REQUEST_TIMEOUT = 12
REQUEST_DELAY = 0.10

# ------------------------------------------------------------
# Risk / trading
# ------------------------------------------------------------

PAPER_MODE = True

LEVERAGE = 3
MARGIN_USDT = 2.0

# بسیار مهم:
# این نسخه هیچ سفارش واقعی ارسال نمی‌کند.
REAL_TRADING = False


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram: credentials missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        if response.ok:
            print("Telegram: OK")
            return True

        print(
            "Telegram error:",
            response.status_code,
            response.text[:500],
        )

    except Exception as exc:
        print("Telegram exception:", exc)

    return False


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
            "User-Agent": "ATI-FUTURES-V2",
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
# MARKET DISCOVERY
# ============================================================

def normalize_symbol(symbol):
    """
    تبدیل نام‌های احتمالی بازار به فرم استاندارد.

    Examples:
        BTC_USDT -> BTCUSDT
        BTC-USDT -> BTCUSDT
        BTC/USDT -> BTCUSDT
        BTCUSDT  -> BTCUSDT
    """

    symbol = str(symbol or "").upper()

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

        # فقط USDT Futures
        if quote and quote != "USDT":
            continue

        if not symbol.endswith("USDT"):
            continue

        # اگر status وجود داشت،
        # فقط TRADING
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
    """
    تلاش برای دریافت کندل از endpointهای شناخته‌شده.
    """

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
        print("   ", error)

    return []


# ============================================================
# CANDLE PARSER
# ============================================================

def candle_close(candle):
    """
    Binance-compatible candle:

    0 = open time
    1 = open
    2 = high
    3 = low
    4 = close
    5 = volume
    """

    if not isinstance(candle, (list, tuple)):
        return None

    if len(candle) < 5:
        return None

    try:
        return float(candle[4])

    except Exception:
        return None


def extract_closed_closes(raw):
    """
    فقط کندل‌های معتبر را استخراج می‌کند.

    مهم:
    آخرین کندل در بسیاری از APIها ممکن است
    هنوز در حال تشکیل باشد.

    بنابراین آخرین کندل را حذف می‌کنیم.
    """

    if not isinstance(raw, list):
        return []

    closes = []

    for candle in raw:

        value = candle_close(candle)

        if value is None:
            continue

        if value <= 0:
            continue

        closes.append(value)

    # حداقل دو کندل لازم است تا بتوانیم
    # کندل جاری را حذف کنیم.
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

    first = sum(
        values[:period]
    ) / period

    result = [first]

    previous = first

    for value in values[period:]:

        current = (
            (
                value - previous
            )
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

    # EMA سریع نسبت به EMA کند جلوتر است.
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

    # کراس صعودی
    bullish_cross = (
        previous_macd
        <= previous_signal
        and
        current_macd
        > current_signal
    )

    # کراس نزولی
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
    print("🤖 ATI FUTURES V2")
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

    # --------------------------------------------------------
    # Credentials
    # --------------------------------------------------------

    if API_KEY:
        print("TABDEAL_API_KEY: OK")
    else:
        print(
            "TABDEAL_API_KEY: MISSING "
            "(not required for public scan)"
        )

    if API_SECRET:
        print("TABDEAL_API_SECRET: OK")
    else:
        print(
            "TABDEAL_API_SECRET: MISSING "
            "(not required for public scan)"
        )

    # --------------------------------------------------------
    # Exchange Info
    # --------------------------------------------------------

    try:

        markets = get_markets()

    except Exception as exc:

        error_text = (
            "❌ ATI FUTURES V2\n\n"
            "ExchangeInfo FAILED\n\n"
            f"Error:\n{exc}"
        )

        print(error_text)

        telegram(error_text)

        return

    if not markets:

        error_text = (
            "❌ ATI FUTURES V2\n\n"
            "No USDT Futures markets found."
        )

        print(error_text)

        telegram(error_text)

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

    # --------------------------------------------------------
    # Scanner
    # --------------------------------------------------------

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
                    f"insufficient closed candles "
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
                })

        except Exception as exc:

            errors += 1

            print(
                f"{symbol}: ERROR: "
                f"{exc}"
            )

        time.sleep(
            REQUEST_DELAY
        )

    # --------------------------------------------------------
    # Runtime
    # --------------------------------------------------------

    runtime = (
        time.time()
        - started
    )

    total_signals = (
        len(buy_signals)
        + len(sell_signals)
    )

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    # --------------------------------------------------------
    # Console summary
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    text = (
        "🤖 ATI FUTURES V2\n\n"
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

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if buy_signals:

        text += "🟢 BUY SIGNALS\n\n"

        for item in buy_signals[:5]:

            text += (
                f"📈 {item['symbol']}\n"
                f"MACD: {fmt(item['macd'])}\n"
                f"Signal: {fmt(item['signal'])}\n"
                f"Histogram: "
                f"{fmt(item['histogram'])}\n\n"
            )

    # --------------------------------------------------------
    # SELL
    # --------------------------------------------------------

    if sell_signals:

        text += "🔴 SELL SIGNALS\n\n"

        for item in sell_signals[:5]:

            text += (
                f"📉 {item['symbol']}\n"
                f"MACD: {fmt(item['macd'])}\n"
                f"Signal: {fmt(item['signal'])}\n"
                f"Histogram: "
                f"{fmt(item['histogram'])}\n\n"
            )

    if not buy_signals and not sell_signals:

        text += (
            "⚪ No new MACD cross\n"
            "on closed 5m candles.\n\n"
        )

    text += (
        f"Time: {now}"
    )

    telegram(text)


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    run()

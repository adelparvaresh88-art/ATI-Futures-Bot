import os
import json
import time
import threading
import requests
from datetime import datetime, timezone

from tabdeal.future import Future
from tabdeal.websocket_client import FutureWebsocketClient


# ============================================================
# ATI FUTURES V5
# Tabdeal Futures | PAPER | MACD 12/26/9 | 5m
# DATA: FUTURES WEBSOCKET
#
# REAL TRADING: DISABLED
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

INTERVAL = "5m"

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

MAX_MARKETS = 30
MIN_CANDLES = 40

PAPER_MODE = True
REAL_TRADING = False

REQUEST_TIMEOUT = 15
TELEGRAM_TIMEOUT = 20

WS_BASE_URL = (
    "wss://api1.tabdeal.org/"
    "special_margin/stream/"
)


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def now_ms():
    return int(
        time.time() * 1000
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN:
        print("Telegram token missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("Telegram chat ID missing")
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=TELEGRAM_TIMEOUT,
        )

        print(
            "Telegram:",
            response.status_code,
        )

        if response.status_code != 200:
            print(response.text[:500])
            return False

        data = response.json()

        if not data.get("ok"):
            print(
                "Telegram error:",
                data,
            )
            return False

        return True

    except Exception as exc:
        print(
            "Telegram exception:",
            repr(exc),
        )
        return False


# ============================================================
# SYMBOL
# ============================================================

def normalize_symbol(symbol):
    return (
        str(symbol or "")
        .upper()
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
    )


def ws_symbol(symbol):
    return normalize_symbol(symbol).lower()


# ============================================================
# FUTURES CLIENT
# ============================================================

def create_future_client():
    return Future(
        API_KEY,
        API_SECRET,
    )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_markets():
    client = create_future_client()

    print(
        "Getting Futures exchange info..."
    )

    data = client.exchange_info()

    if not isinstance(data, dict):
        raise RuntimeError(
            "Invalid Futures exchangeInfo"
        )

    symbols = data.get(
        "symbols",
        [],
    )

    if not isinstance(symbols, list):
        raise RuntimeError(
            "exchangeInfo symbols is not a list"
        )

    markets = []

    for item in symbols:
        if not isinstance(item, dict):
            continue

        raw_symbol = item.get(
            "symbol",
            "",
        )

        symbol = normalize_symbol(
            raw_symbol
        )

        quote = str(
            item.get(
                "quoteAsset",
                "",
            )
        ).upper()

        status = str(
            item.get(
                "status",
                "",
            )
        ).upper()

        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        if quote and quote != "USDT":
            continue

        if status and status != "TRADING":
            continue

        if symbol not in markets:
            markets.append(symbol)

    markets.sort()

    return markets[:MAX_MARKETS]


# ============================================================
# CANDLE STORAGE
# ============================================================

candles = {}

candles_lock = threading.Lock()

ws_client = None


def ensure_symbol(symbol):
    with candles_lock:
        if symbol not in candles:
            candles[symbol] = {}


def save_candle(
    symbol,
    open_time,
    close_price,
    closed,
):
    symbol = normalize_symbol(symbol)

    if not symbol:
        return

    try:
        open_time = int(open_time)
        close_price = float(close_price)
    except Exception:
        return

    if close_price <= 0:
        return

    ensure_symbol(symbol)

    with candles_lock:
        candles[symbol][open_time] = {
            "close": close_price,
            "closed": bool(closed),
        }

        # جلوگیری از رشد بی‌نهایت حافظه
        keys = sorted(
            candles[symbol].keys()
        )

        if len(keys) > 250:
            for key in keys[:-200]:
                candles[symbol].pop(
                    key,
                    None,
                )


# ============================================================
# WEBSOCKET MESSAGE PARSER
# ============================================================

def parse_message(message):
    try:
        data = json.loads(message)
    except Exception:
        return

    if not isinstance(data, dict):
        return

    # پیام‌های acknowledge
    if "result" in data and "id" in data:
        return

    stream = data.get(
        "stream",
        "",
    )

    payload = data.get(
        "data",
        data,
    )

    if not isinstance(payload, dict):
        return

    # --------------------------------------------------------
    # حالت kline
    # --------------------------------------------------------

    kline = payload.get("k")

    if isinstance(kline, dict):
        symbol = (
            kline.get("s")
            or payload.get("s")
            or ""
        )

        open_time = (
            kline.get("t")
            or kline.get("T")
        )

        close_price = (
            kline.get("c")
        )

        closed = (
            kline.get("x", False)
        )

        save_candle(
            symbol,
            open_time,
            close_price,
            closed,
        )

        return

    # --------------------------------------------------------
    # بعضی ساختارهای احتمالی
    # --------------------------------------------------------

    if "openTime" in payload:
        symbol = payload.get(
            "s",
            payload.get(
                "symbol",
                "",
            ),
        )

        close_price = payload.get(
            "c",
            payload.get(
                "close",
                None,
            ),
        )

        save_candle(
            symbol,
            payload.get(
                "openTime"
            ),
            close_price,
            payload.get(
                "closed",
                payload.get(
                    "x",
                    False,
                ),
            ),
        )

        return

    # --------------------------------------------------------
    # لاگ محدود برای تشخیص ساختار
    # --------------------------------------------------------

    if stream:
        print(
            "WS message:",
            stream,
            str(payload)[:500],
        )


# ============================================================
# WEBSOCKET CALLBACK
# ============================================================

def websocket_callback(message):
    try:
        parse_message(message)
    except Exception as exc:
        print(
            "WS parser error:",
            repr(exc),
        )


# ============================================================
# WEBSOCKET SUBSCRIBE
# ============================================================

def start_websocket(markets):
    global ws_client

    if not markets:
        raise RuntimeError(
            "No markets for websocket"
        )

    params = []

    for symbol in markets:
        s = ws_symbol(symbol)

        # Topic استاندارد kline
        params.append(
            f"{s}@kline_{INTERVAL}"
        )

    payload = {
        "method": "SUBSCRIBE",
        "params": params,
        "id": 1,
    }

    print()
    print("=" * 64)
    print("STARTING FUTURES WEBSOCKET")
    print("=" * 64)

    print(
        "URL:",
        WS_BASE_URL,
    )

    print(
        "Subscriptions:",
        len(params),
    )

    print(
        "First topics:",
        params[:5],
    )

    ws_client = FutureWebsocketClient(
        base_url=WS_BASE_URL
    )

    ws_client.subscribe(
        callback=websocket_callback,
        payload=payload,
    )

    return ws_client


# ============================================================
# CLOSED CANDLES
# ============================================================

def get_closed_closes(symbol):
    symbol = normalize_symbol(symbol)

    with candles_lock:
        data = candles.get(
            symbol,
            {},
        )

        rows = []

        for open_time, item in data.items():
            if not item.get(
                "closed",
                False,
            ):
                continue

            rows.append(
                (
                    open_time,
                    float(
                        item["close"]
                    ),
                )
            )

    rows.sort(
        key=lambda x: x[0]
    )

    return [
        close
        for _, close in rows
    ]


# ============================================================
# EMA
# ============================================================

def ema(values, period):
    if len(values) < period:
        return []

    multiplier = (
        2.0
        / (period + 1)
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

        result.append(current)
        previous = current

    return result


# ============================================================
# MACD
# ============================================================

def calculate_macd(closes):
    if len(closes) < MIN_CANDLES:
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

    if count < (
        MACD_SIGNAL + 2
    ):
        return None

    fast_aligned = (
        fast_aligned[-count:]
    )

    slow = slow[-count:]

    macd_line = []

    for f, s in zip(
        fast_aligned,
        slow,
    ):
        macd_line.append(
            f - s
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

    return {
        "macd": current_macd,
        "signal": current_signal,
        "histogram": (
            current_macd
            - current_signal
        ),
        "previous_macd":
            previous_macd,
        "previous_signal":
            previous_signal,
    }


# ============================================================
# SIGNAL
# ============================================================

def get_signal(macd):
    if not macd:
        return None

    if (
        macd["previous_macd"]
        <= macd["previous_signal"]
        and
        macd["macd"]
        > macd["signal"]
    ):
        return "BUY"

    if (
        macd["previous_macd"]
        >= macd["previous_signal"]
        and
        macd["macd"]
        < macd["signal"]
    ):
        return "SELL"

    return None


# ============================================================
# FORMAT
# ============================================================

def fmt(value):
    try:
        return f"{float(value):.8f}"
    except Exception:
        return "-"


# ============================================================
# MAIN
# ============================================================

def run():
    start = time.time()

    print()
    print("=" * 64)
    print("ATI FUTURES V5")
    print("=" * 64)

    print(
        "Mode: PAPER"
    )
    print(
        "Exchange: Tabdeal Futures"
    )
    print(
        "MACD: 12/26/9"
    )
    print(
        "Timeframe: 5m"
    )
    print(
        "Data: Futures WebSocket"
    )
    print(
        "Real orders: DISABLED"
    )
    print(
        "Time:",
        utc_now(),
    )

    # --------------------------------------------------------
    # Markets
    # --------------------------------------------------------

    try:
        markets = get_markets()

    except Exception as exc:
        print(
            "Exchange info ERROR:",
            repr(exc),
        )

        telegram(
            "🚨 ATI FUTURES V5\n\n"
            "Exchange info ERROR\n\n"
            f"{exc}\n\n"
            f"Time: {utc_now()}"
        )

        return

    print()
    print(
        "Markets:",
        len(markets),
    )

    if not markets:
        print(
            "No Futures markets found."
        )
        return

    # --------------------------------------------------------
    # Start WS
    # --------------------------------------------------------

    try:
        start_websocket(
            markets
        )

    except Exception as exc:
        print(
            "WebSocket ERROR:",
            repr(exc),
        )

        telegram(
            "🚨 ATI FUTURES V5\n\n"
            "WebSocket ERROR\n\n"
            f"{exc}"
        )

        return

    # --------------------------------------------------------
    # Give WS time
    # --------------------------------------------------------

    print()
    print(
        "Waiting for Futures "
        "5m candle data..."
    )

    # برای GitHub Actions، چند ثانیه
    # برای دریافت stream فرصت می‌دهیم.
    time.sleep(20)

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    checked = 0
    macd_ready = 0
    errors = 0

    buy_signals = []
    sell_signals = []

    for symbol in markets:
        checked += 1

        try:
            closes = get_closed_closes(
                symbol
            )

            print(
                f"{symbol}: "
                f"{len(closes)} closed candles"
            )

            if len(closes) < MIN_CANDLES:
                continue

            macd = calculate_macd(
                closes
            )

            if not macd:
                continue

            macd_ready += 1

            signal = get_signal(
                macd
            )

            print(
                f"{symbol}: "
                f"MACD={fmt(macd['macd'])} "
                f"Signal={fmt(macd['signal'])} "
                f"Hist={fmt(macd['histogram'])} "
                f"Cross={signal or '-'}"
            )

            if signal == "BUY":
                buy_signals.append(
                    (
                        symbol,
                        macd,
                    )
                )

            elif signal == "SELL":
                sell_signals.append(
                    (
                        symbol,
                        macd,
                    )
                )

        except Exception as exc:
            errors += 1

            print(
                f"{symbol}: ERROR:",
                repr(exc),
            )

    # --------------------------------------------------------
    # Report
    # --------------------------------------------------------

    runtime = (
        time.time()
        - start
    )

    lines = [
        "🤖 ATI FUTURES V5",
        "",
        "Mode: 🟢 PAPER",
        "Exchange: Tabdeal Futures",
        "MACD: 12/26/9",
        "Timeframe: 5m",
        "Data: Futures WebSocket",
        "Real orders: DISABLED",
        "",
        f"Markets: {len(markets)}",
        f"Checked: {checked}",
        f"MACD ready: {macd_ready}",
        f"BUY signals: {len(buy_signals)}",
        f"SELL signals: {len(sell_signals)}",
        f"Errors: {errors}",
        f"Runtime: {runtime:.1f}s",
        f"Time: {utc_now()}",
    ]

    if buy_signals:
        lines.append("")
        lines.append(
            "🟢 BUY SIGNALS"
        )

        for symbol, macd in buy_signals:
            lines.append(
                f"{symbol} | "
                f"MACD {fmt(macd['macd'])} | "
                f"Signal {fmt(macd['signal'])}"
            )

    if sell_signals:
        lines.append("")
        lines.append(
            "🔴 SELL SIGNALS"
        )

        for symbol, macd in sell_signals:
            lines.append(
                f"{symbol} | "
                f"MACD {fmt(macd['macd'])} | "
                f"Signal {fmt(macd['signal'])}"
            )

    if (
        not buy_signals
        and not sell_signals
    ):
        lines.append("")
        lines.append(
            "⚪ No new MACD crossover signal."
        )

    report = "\n".join(lines)

    print()
    print("=" * 64)
    print(report)
    print("=" * 64)

    telegram(report)

    # --------------------------------------------------------
    # Stop WS
    # --------------------------------------------------------

    global ws_client

    try:
        if ws_client:
            ws_client.stop()
    except Exception as exc:
        print(
            "WS stop error:",
            repr(exc),
        )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    try:
        run()

    except KeyboardInterrupt:
        print(
            "Interrupted."
        )

    except Exception as exc:
        print()
        print(
            "FATAL ERROR:",
            repr(exc),
        )

        telegram(
            "🚨 ATI FUTURES V5 FATAL ERROR\n\n"
            f"{exc}\n\n"
            f"Time: {utc_now()}"
        )

        raise

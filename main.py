import os
import json
import time
import math
import hmac
import hashlib
import requests
from datetime import datetime, timezone

# ============================================================
# ATI FUTURES BOT V8
# Tabdeal Futures
# 5m candles built from live trades
# MACD 12/26/9
# PAPER MODE
# ============================================================

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BASE_URL = "https://api1.tabdeal.org"
WS_URL = "wss://api1.tabdeal.org/special_margin/stream/"

PAPER_MODE = True
LEVERAGE = 3
MARGIN_USDT = 2.0

TIMEFRAME_MINUTES = 5

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

MAX_MARKETS = 30
MAX_CANDLES = 200
REQUEST_TIMEOUT = 15

RUN_SECONDS = 240
TRADE_POLL_SECONDS = 3

STATE_FILE = "ati_state.json"


# ============================================================
# LOG
# ============================================================

def log(message):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] {message}", flush=True)


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        url = (
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )
    except Exception as e:
        log(f"Telegram error: {e}")


# ============================================================
# SIGNATURE
# ============================================================

def sign_params(params):
    query = "&".join(
        f"{k}={params[k]}"
        for k in sorted(params)
    )

    return hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()


# ============================================================
# REST REQUEST
# ============================================================

def public_get(path, params=None):
    url = BASE_URL + path

    try:
        response = requests.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            log(
                f"HTTP {response.status_code} "
                f"{path} -> {response.text[:300]}"
            )
            return None

        return response.json()

    except Exception as e:
        log(f"GET error {path}: {e}")
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
        data = public_get(path)

        if data:
            log(f"ExchangeInfo OK: {path}")
            return data

    return None


# ============================================================
# MARKET EXTRACTION
# ============================================================

def extract_markets(data):

    if not isinstance(data, dict):
        return []

    raw = (
        data.get("symbols")
        or data.get("data")
        or data.get("markets")
        or []
    )

    markets = []

    if isinstance(raw, dict):
        raw = list(raw.values())

    for item in raw:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("contract")
            or item.get("pair")
            or item.get("market")
        )

        if not symbol:
            continue

        symbol = str(symbol).upper()

        status = str(
            item.get("status", "TRADING")
        ).upper()

        quote = str(
            item.get("quoteAsset")
            or item.get("quote")
            or ""
        ).upper()

        if status not in ("TRADING", "OPEN", ""):
            continue

        if quote and quote != "USDT":
            continue

        if not (
            symbol.endswith("USDT")
            or symbol.endswith("_USDT")
        ):
            continue

        if symbol not in markets:
            markets.append(symbol)

    return markets


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def ws_symbol(symbol):
    return symbol.upper()


def rest_symbol(symbol):
    return symbol.replace("_", "").upper()


# ============================================================
# STATE
# ============================================================

def load_state():

    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

    except Exception as e:
        log(f"State load error: {e}")

    return {}


def save_state(state):

    try:
        tmp = STATE_FILE + ".tmp"

        with open(
            tmp,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                state,
                f,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        os.replace(tmp, STATE_FILE)

    except Exception as e:
        log(f"State save error: {e}")


# ============================================================
# EMA
# ============================================================

def ema(values, period):

    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)

    result = []

    seed = sum(values[:period]) / period

    result.append(seed)

    previous = seed

    for value in values[period:]:

        current = (
            (value - previous) * multiplier
            + previous
        )

        result.append(current)

        previous = current

    return result


# ============================================================
# MACD
# ============================================================

def calculate_macd(closes):

    if len(closes) < MACD_SLOW + MACD_SIGNAL:
        return None

    fast = ema(closes, MACD_FAST)
    slow = ema(closes, MACD_SLOW)

    if not fast or not slow:
        return None

    offset = MACD_SLOW - MACD_FAST

    macd_values = []

    for i in range(len(slow)):

        fast_index = i + offset

        if fast_index < 0:
            continue

        if fast_index >= len(fast):
            break

        macd_values.append(
            fast[fast_index] - slow[i]
        )

    if len(macd_values) < MACD_SIGNAL + 2:
        return None

    signal = ema(
        macd_values,
        MACD_SIGNAL,
    )

    if len(signal) < 2:
        return None

    macd_current = macd_values[-1]

    macd_previous = macd_values[-2]

    signal_current = signal[-1]

    signal_previous = signal[-2]

    return {
        "macd": macd_current,
        "previous_macd": macd_previous,
        "signal": signal_current,
        "previous_signal": signal_previous,
    }


# ============================================================
# SIGNAL
# ============================================================

def macd_signal(closes):

    result = calculate_macd(closes)

    if not result:
        return None

    macd_now = result["macd"]
    macd_prev = result["previous_macd"]

    signal_now = result["signal"]
    signal_prev = result["previous_signal"]

    bullish_cross = (
        macd_prev <= signal_prev
        and macd_now > signal_now
    )

    bearish_cross = (
        macd_prev >= signal_prev
        and macd_now < signal_now
    )

    if bullish_cross:
        return "BUY"

    if bearish_cross:
        return "SELL"

    return None


# ============================================================
# CANDLE ENGINE
# ============================================================

def candle_bucket(timestamp_ms):

    interval = TIMEFRAME_MINUTES * 60 * 1000

    return (
        int(timestamp_ms) // interval
    ) * interval


def new_candle(timestamp_ms, price, qty=0):

    return {
        "time": candle_bucket(timestamp_ms),
        "open": float(price),
        "high": float(price),
        "low": float(price),
        "close": float(price),
        "volume": float(qty or 0),
    }


def update_candle(candle, price, qty=0):

    price = float(price)

    candle["high"] = max(
        candle["high"],
        price,
    )

    candle["low"] = min(
        candle["low"],
        price,
    )

    candle["close"] = price

    candle["volume"] += float(
        qty or 0
    )


def add_trade(
    state,
    symbol,
    timestamp_ms,
    price,
    qty=0,
):

    symbol_state = state.setdefault(
        symbol,
        {
            "candles": [],
            "current": None,
            "last_signal_candle": None,
        },
    )

    bucket = candle_bucket(
        timestamp_ms
    )

    current = symbol_state.get(
        "current"
    )

    if current is None:

        symbol_state["current"] = new_candle(
            timestamp_ms,
            price,
            qty,
        )

        return None

    if bucket == current["time"]:

        update_candle(
            current,
            price,
            qty,
        )

        return None

    if bucket > current["time"]:

        closed = current.copy()

        symbol_state["candles"].append(
            closed
        )

        symbol_state["candles"] = (
            symbol_state["candles"][
                -MAX_CANDLES:
            ]
        )

        symbol_state["current"] = new_candle(
            timestamp_ms,
            price,
            qty,
        )

        return closed

    return None


# ============================================================
# GENERIC TRADE PARSER
# ============================================================

def find_number(obj, keys):

    if not isinstance(obj, dict):
        return None

    for key in keys:

        value = obj.get(key)

        if value is None:
            continue

        try:
            return float(value)
        except Exception:
            pass

    return None


def find_timestamp(obj):

    if not isinstance(obj, dict):
        return None

    keys = [
        "T",
        "E",
        "timestamp",
        "time",
        "ts",
        "eventTime",
        "transactTime",
        "tradeTime",
    ]

    for key in keys:

        value = obj.get(key)

        if value is None:
            continue

        try:
            value = int(float(value))

            if value < 10_000_000_000:
                value *= 1000

            return value

        except Exception:
            pass

    return int(
        time.time() * 1000
    )


def parse_trade_message(message):

    if not isinstance(message, dict):
        return None

    candidates = [message]

    for key in (
        "data",
        "result",
        "tick",
        "trade",
        "payload",
    ):

        value = message.get(key)

        if isinstance(value, dict):
            candidates.append(value)

        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    candidates.append(item)

    for obj in candidates:

        price = find_number(
            obj,
            [
                "p",
                "price",
                "lastPrice",
                "last",
                "P",
            ],
        )

        if price is None or price <= 0:
            continue

        qty = find_number(
            obj,
            [
                "q",
                "qty",
                "quantity",
                "volume",
                "size",
                "v",
            ],
        ) or 0

        timestamp = find_timestamp(obj)

        symbol = (
            obj.get("s")
            or obj.get("symbol")
            or obj.get("S")
            or obj.get("market")
        )

        if symbol:

            symbol = str(symbol).upper()

        return {
            "symbol": symbol,
            "price": price,
            "qty": qty,
            "time": timestamp,
        }

    return None


# ============================================================
# WEBSOCKET
# ============================================================

def websocket_collect(symbols, state):

    try:
        import websocket
    except ImportError:
        log("websocket-client not installed")
        return 0

    received = 0

    ws = None

    try:

        log(
            f"Connecting WebSocket: {WS_URL}"
        )

        ws = websocket.create_connection(
            WS_URL,
            timeout=10,
            enable_multithread=True,
        )

        ws.settimeout(5)

        # ----------------------------------------------------
        # Try common Tabdeal subscription formats.
        # The first accepted response/data will determine use.
        # ----------------------------------------------------

        subscriptions = []

        for symbol in symbols:

            s = ws_symbol(symbol)

            subscriptions.append(
                f"trade@{s}"
            )

        payloads = [
            {
                "method": "SUBSCRIBE",
                "params": subscriptions,
                "id": 1,
            },
            {
                "method": "SUBSCRIBE",
                "params": subscriptions,
            },
            {
                "op": "subscribe",
                "args": subscriptions,
            },
        ]

        # Send first format.
        ws.send(
            json.dumps(payloads[0])
        )

        log(
            f"WS subscribed: {len(symbols)} markets"
        )

        end_time = time.time() + RUN_SECONDS

        while time.time() < end_time:

            try:

                raw = ws.recv()

                if not raw:
                    continue

                if isinstance(raw, bytes):
                    raw = raw.decode(
                        "utf-8",
                        errors="ignore",
                    )

                try:
                    message = json.loads(raw)
                except Exception:
                    continue

                trade = parse_trade_message(
                    message
                )

                if not trade:
                    continue

                symbol = trade["symbol"]

                if not symbol:
                    continue

                normalized = symbol.replace(
                    "_",
                    "",
                )

                wanted = {
                    s.replace("_", "").upper()
                    for s in symbols
                }

                if normalized not in wanted:
                    continue

                # Find original symbol format.
                actual_symbol = None

                for s in symbols:

                    if (
                        s.replace("_", "").upper()
                        == normalized
                    ):
                        actual_symbol = s
                        break

                if not actual_symbol:
                    continue

                closed = add_trade(
                    state,
                    actual_symbol,
                    trade["time"],
                    trade["price"],
                    trade["qty"],
                )

                received += 1

                if closed:

                    candles = state[
                        actual_symbol
                    ]["candles"]

                    closes = [
                        float(x["close"])
                        for x in candles
                    ]

                    if len(closes) >= (
                        MACD_SLOW + MACD_SIGNAL + 2
                    ):

                        signal = macd_signal(
                            closes
                        )

                        if signal:

                            candle_time = closed[
                                "time"
                            ]

                            last_signal = state[
                                actual_symbol
                            ].get(
                                "last_signal_candle"
                            )

                            if last_signal != candle_time:

                                state[
                                    actual_symbol
                                ][
                                    "last_signal_candle"
                                ] = candle_time

                                log(
                                    f"🚨 {signal} "
                                    f"{actual_symbol} "
                                    f"price={closed['close']}"
                                )

                                telegram(
                                    f"🤖 ATI FUTURES V8\n\n"
                                    f"Signal: {signal}\n"
                                    f"Symbol: {actual_symbol}\n"
                                    f"Price: {closed['close']}\n"
                                    f"MACD: 12/26/9\n"
                                    f"TF: 5m\n"
                                    f"Mode: PAPER"
                                )

            except Exception as e:

                text = str(e).lower()

                if (
                    "timed out" in text
                    or "timeout" in text
                ):
                    continue

                log(
                    f"WS receive error: {e}"
                )

                break

    except Exception as e:

        log(
            f"WebSocket connection error: {e}"
        )

    finally:

        if ws:

            try:
                ws.close()
            except Exception:
                pass

    return received


# ============================================================
# FALLBACK: DEPTH / LAST PRICE
# ============================================================

def get_last_price(symbol):

    paths = [
        "/r/fapi/v1/depth",
        "/fapi/v1/depth",
    ]

    for path in paths:

        data = public_get(
            path,
            {
                "symbol": rest_symbol(symbol),
                "limit": 5,
            },
        )

        if not isinstance(data, dict):
            continue

        bids = data.get("bids") or []
        asks = data.get("asks") or []

        prices = []

        if bids:
            try:
                prices.append(
                    float(bids[0][0])
                )
            except Exception:
                pass

        if asks:
            try:
                prices.append(
                    float(asks[0][0])
                )
            except Exception:
                pass

        if prices:
            return sum(prices) / len(prices)

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    log("=" * 60)
    log("🤖 ATI FUTURES V8")
    log("Tabdeal Futures")
    log("5m candles from trades")
    log("MACD 12/26/9")
    log(
        f"Mode: {'PAPER' if PAPER_MODE else 'REAL'}"
    )
    log("=" * 60)

    if not API_KEY or not API_SECRET:

        log(
            "WARNING: TABDEAL API credentials missing"
        )

    state = load_state()

    exchange_info = get_exchange_info()

    if not exchange_info:

        log(
            "❌ ExchangeInfo failed"
        )

        telegram(
            "❌ ATI FUTURES V8\nExchangeInfo failed"
        )

        return

    markets = extract_markets(
        exchange_info
    )

    if not markets:

        log(
            "❌ No USDT futures markets found"
        )

        log(
            str(exchange_info)[:1000]
        )

        return

    markets = markets[
        :MAX_MARKETS
    ]

    log(
        f"Markets: {len(markets)}"
    )

    # Initialize state.
    for symbol in markets:

        state.setdefault(
            symbol,
            {
                "candles": [],
                "current": None,
                "last_signal_candle": None,
            },
        )

    save_state(state)

    # --------------------------------------------------------
    # WebSocket
    # --------------------------------------------------------

    received = websocket_collect(
        markets,
        state,
    )

    save_state(state)

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    total_candles = 0
    macd_ready = 0

    for symbol in markets:

        candles = state[
            symbol
        ].get(
            "candles",
            [],
        )

        total_candles += len(candles)

        if len(candles) >= (
            MACD_SLOW
            + MACD_SIGNAL
            + 2
        ):
            macd_ready += 1

    runtime = time.time() - started

    log("=" * 60)
    log("ATI FUTURES V8 RESULT")
    log("=" * 60)

    log(
        f"Mode: {'PAPER' if PAPER_MODE else 'REAL'}"
    )

    log(
        "Exchange: Tabdeal Futures"
    )

    log(
        "MACD: 12/26/9"
    )

    log(
        "Timeframe: 5m"
    )

    log(
        f"Markets: {len(markets)}"
    )

    log(
        f"Trades received: {received}"
    )

    log(
        f"Closed candles: {total_candles}"
    )

    log(
        f"MACD ready: {macd_ready}"
    )

    log(
        f"Runtime: {runtime:.1f}s"
    )

    log("=" * 60)

    telegram(
        "🤖 ATI FUTURES V8\n\n"
        f"Mode: {'PAPER' if PAPER_MODE else 'REAL'}\n"
        f"Markets: {len(markets)}\n"
        f"Trades: {received}\n"
        f"Closed candles: {total_candles}\n"
        f"MACD ready: {macd_ready}\n"
        f"Runtime: {runtime:.1f}s"
    )


if __name__ == "__main__":
    main()

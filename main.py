import os
import json
import time
import requests
from datetime import datetime, timezone

API_KEY = os.getenv("TABDEAL_API_KEY", "")
API_SECRET = os.getenv("TABDEAL_API_SECRET", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BASE_URL = "https://api1.tabdeal.org"
WS_URL = "wss://api1.tabdeal.org/special_margin/stream/"

PAPER_MODE = True

MAX_MARKETS = 30
MAX_CANDLES = 200

TIMEFRAME_MS = 5 * 60 * 1000

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

RUN_SECONDS = 180
REQUEST_TIMEOUT = 15

STATE_FILE = "ati_state.json"


def log(text):
    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )
    print(f"[{now}] {text}", flush=True)


def telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )
    except Exception as e:
        log(f"Telegram error: {e}")


def public_get(path, params=None):
    try:
        r = requests.get(
            BASE_URL + path,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        log(
            f"GET {path} -> {r.status_code}"
        )

        if r.status_code != 200:
            log(r.text[:500])
            return None

        return r.json()

    except Exception as e:
        log(f"GET error: {e}")
        return None


def get_exchange_info():

    for path in (
        "/r/fapi/v1/exchangeInfo",
        "/fapi/v1/exchangeInfo",
    ):

        data = public_get(path)

        if data:
            return data

    return None


def get_markets(data):

    if not isinstance(data, dict):
        return []

    raw = data.get("symbols") or []

    markets = []

    for item in raw:

        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("symbol", "")
        ).upper()

        status = str(
            item.get("status", "TRADING")
        ).upper()

        quote = str(
            item.get("quoteAsset", "")
        ).upper()

        if not symbol:
            continue

        if status not in ("TRADING", "OPEN"):
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

    return markets[:MAX_MARKETS]


def load_state():

    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except Exception:
        return {}


def save_state(state):

    try:
        with open(
            STATE_FILE,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                state,
                f,
                ensure_ascii=False,
            )
    except Exception as e:
        log(f"State save error: {e}")


def ema(values, period):

    if len(values) < period:
        return []

    multiplier = 2.0 / (period + 1)

    result = [
        sum(values[:period]) / period
    ]

    for value in values[period:]:
        result.append(
            (
                value - result[-1]
            ) * multiplier
            + result[-1]
        )

    return result


def calculate_macd(closes):

    if len(closes) < 40:
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
        MACD_SLOW - MACD_FAST
    )

    macd = []

    for i, slow_value in enumerate(slow):

        fi = i + offset

        if fi >= len(fast):
            break

        macd.append(
            fast[fi] - slow_value
        )

    signal = ema(
        macd,
        MACD_SIGNAL,
    )

    if len(macd) < 2 or len(signal) < 2:
        return None

    return {
        "macd": macd[-1],
        "prev_macd": macd[-2],
        "signal": signal[-1],
        "prev_signal": signal[-2],
    }


def get_signal(closes):

    result = calculate_macd(closes)

    if not result:
        return None

    bullish = (
        result["prev_macd"]
        <= result["prev_signal"]
        and
        result["macd"]
        > result["signal"]
    )

    bearish = (
        result["prev_macd"]
        >= result["prev_signal"]
        and
        result["macd"]
        < result["signal"]
    )

    if bullish:
        return "BUY"

    if bearish:
        return "SELL"

    return None


def bucket(ts):

    return (
        int(ts)
        // TIMEFRAME_MS
    ) * TIMEFRAME_MS


def update_price(
    state,
    symbol,
    timestamp,
    price,
):

    symbol_state = state.setdefault(
        symbol,
        {
            "candles": [],
            "current": None,
            "last_signal": None,
        },
    )

    b = bucket(timestamp)

    current = symbol_state.get(
        "current"
    )

    if current is None:

        symbol_state["current"] = {
            "time": b,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
        }

        return None

    if b == current["time"]:

        current["high"] = max(
            current["high"],
            price,
        )

        current["low"] = min(
            current["low"],
            price,
        )

        current["close"] = price

        return None

    if b > current["time"]:

        closed = current.copy()

        symbol_state[
            "candles"
        ].append(closed)

        symbol_state[
            "candles"
        ] = symbol_state[
            "candles"
        ][-MAX_CANDLES:]

        symbol_state["current"] = {
            "time": b,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
        }

        return closed

    return None


def parse_depth(message):

    if not isinstance(message, dict):
        return None

    symbol = (
        message.get("s")
        or message.get("symbol")
    )

    data = message.get("data")

    if isinstance(data, dict):

        symbol = (
            data.get("s")
            or data.get("symbol")
            or symbol
        )

        message = data

    if not symbol:
        return None

    bids = (
        message.get("b")
        or message.get("bids")
    )

    asks = (
        message.get("a")
        or message.get("asks")
    )

    if not bids or not asks:
        return None

    try:
        bid = float(bids[0][0])
        ask = float(asks[0][0])

        if bid <= 0 or ask <= 0:
            return None

        price = (
            bid + ask
        ) / 2.0

    except Exception:
        return None

    timestamp = (
        message.get("E")
        or message.get("T")
        or message.get("timestamp")
        or int(time.time() * 1000)
    )

    try:
        timestamp = int(timestamp)
    except Exception:
        timestamp = int(
            time.time() * 1000
        )

    return (
        str(symbol).upper(),
        timestamp,
        price,
    )


def run_websocket(
    markets,
    state,
):

    try:
        import websocket
    except ImportError:
        log(
            "ERROR: websocket-client not installed"
        )
        return 0, 0

    messages = 0
    closed_candles = 0

    try:

        log(
            f"Connecting: {WS_URL}"
        )

        ws = websocket.create_connection(
            WS_URL,
            timeout=10,
        )

        ws.settimeout(5)

        params = [
            f"{symbol}@depth@2000ms"
            for symbol in markets
        ]

        payload = {
            "method": "SUBSCRIBE",
            "id": 1,
            "params": params,
        }

        log(
            f"Subscribing to {len(params)} depth streams"
        )

        ws.send(
            json.dumps(payload)
        )

        end = (
            time.time()
            + RUN_SECONDS
        )

        while time.time() < end:

            try:

                raw = ws.recv()

                if not raw:
                    continue

                if isinstance(raw, bytes):
                    raw = raw.decode(
                        "utf-8",
                        errors="ignore",
                    )

                log(
                    f"WS RAW: {raw[:350]}"
                )

                try:
                    message = json.loads(raw)
                except Exception:
                    continue

                parsed = parse_depth(
                    message
                )

                if not parsed:
                    continue

                symbol, timestamp, price = parsed

                normalized = symbol.replace(
                    "_",
                    "",
                )

                matched = None

                for market in markets:

                    if (
                        market.replace(
                            "_",
                            "",
                        ).upper()
                        == normalized
                    ):
                        matched = market
                        break

                if not matched:
                    continue

                messages += 1

                closed = update_price(
                    state,
                    matched,
                    timestamp,
                    price,
                )

                if closed:

                    closed_candles += 1

                    candles = state[
                        matched
                    ]["candles"]

                    closes = [
                        float(c["close"])
                        for c in candles
                    ]

                    log(
                        f"CANDLE {matched} "
                        f"{len(closes)} "
                        f"O={closed['open']} "
                        f"H={closed['high']} "
                        f"L={closed['low']} "
                        f"C={closed['close']}"
                    )

                    signal = get_signal(
                        closes
                    )

                    if signal:

                        candle_id = closed[
                            "time"
                        ]

                        previous = state[
                            matched
                        ].get(
                            "last_signal"
                        )

                        if previous != candle_id:

                            state[
                                matched
                            ][
                                "last_signal"
                            ] = candle_id

                            log(
                                f"🚨 {signal} "
                                f"{matched} "
                                f"{closed['close']}"
                            )

                            telegram(
                                "🤖 ATI FUTURES V9\n\n"
                                f"Signal: {signal}\n"
                                f"Symbol: {matched}\n"
                                f"Price: {closed['close']}\n"
                                "MACD: 12/26/9\n"
                                "TF: 5m\n"
                                "Mode: PAPER"
                            )

            except Exception as e:

                text = str(e).lower()

                if (
                    "timeout" in text
                    or "timed out" in text
                ):
                    continue

                log(
                    f"WS receive error: {e}"
                )

                break

        ws.close()

    except Exception as e:

        log(
            f"WS ERROR: {type(e).__name__}: {e}"
        )

    return messages, closed_candles


def main():

    start = time.time()

    log("=" * 60)
    log("🤖 ATI FUTURES V9")
    log("Tabdeal Futures")
    log("Official Depth WebSocket")
    log("5m synthetic candles")
    log("MACD 12/26/9")
    log("PAPER MODE")
    log("=" * 60)

    info = get_exchange_info()

    if not info:

        log(
            "❌ ExchangeInfo failed"
        )

        return

    markets = get_markets(info)

    log(
        f"Markets: {len(markets)}"
    )

    if not markets:
        log(
            "❌ No USDT markets"
        )
        return

    state = load_state()

    for symbol in markets:

        state.setdefault(
            symbol,
            {
                "candles": [],
                "current": None,
                "last_signal": None,
            },
        )

    messages, closed = run_websocket(
        markets,
        state,
    )

    save_state(state)

    macd_ready = 0
    total_candles = 0

    for symbol in markets:

        candles = state[
            symbol
        ].get(
            "candles",
            [],
        )

        total_candles += len(candles)

        if len(candles) >= 40:
            macd_ready += 1

    runtime = (
        time.time()
        - start
    )

    log("=" * 60)
    log("ATI FUTURES V9 RESULT")
    log("=" * 60)

    log(
        f"Markets: {len(markets)}"
    )

    log(
        f"Depth messages: {messages}"
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
        "🤖 ATI FUTURES V9\n\n"
        "Mode: PAPER\n"
        f"Markets: {len(markets)}\n"
        f"Depth messages: {messages}\n"
        f"Closed candles: {total_candles}\n"
        f"MACD ready: {macd_ready}\n"
        f"Runtime: {runtime:.1f}s"
    )


if __name__ == "__main__":
    main()

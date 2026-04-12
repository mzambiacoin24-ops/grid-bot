import time
import hmac
import hashlib
import base64
import json
import requests
from datetime import datetime, timezone

OKX_API_KEY = "a0457663-9fdc-4787-b27e-5b7b7f34e99b"
OKX_SECRET = "B803CF81AB7DCFD262399F893D755497"
OKX_PASSPHRASE = "Futuresbot2026."

TELEGRAM_TOKEN = "8632951293:AAF1hhp3hz-ZjgJwaMmfAozEgbpxK9yCsNo"
TELEGRAM_CHAT_ID = "7010983039"

BASE_URL = "https://www.okx.com"

DRY_RUN = False

GRID_COUNT = 10
GRID_SPREAD = 0.004
REBALANCE_THRESHOLD = 0.015
SCAN_INTERVAL = 3600
CHECK_INTERVAL = 10

MIN_VOLUME_USD = 100_000
MIN_CHANGE_PCT = 0.5
MAX_CHANGE_PCT = 20.0
MIN_PRICE = 0.0001
MAX_PRICE = 200.0

BLACKLIST = ["USDC", "USDT", "BUSD", "DAI", "TUSD", "USDP"]

total_pnl = 0.0
trade_count = 0
current_symbol = None
initial_balance = 0.0

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        log(f"Telegram error: {e}")

def get_headers(method, path, body=""):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    message = ts + method.upper() + path + body
    sig = base64.b64encode(
        hmac.new(OKX_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    ).decode()
    return {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": sig,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type": "application/json"
    }

def get_balance():
    try:
        path = "/api/v5/account/balance?ccy=USDT"
        headers = get_headers("GET", path)
        r = requests.get(BASE_URL + path, headers=headers, timeout=10)
        data = r.json()
        details = data.get("data", [{}])[0].get("details", [])
        for d in details:
            if d.get("ccy") == "USDT":
                return float(d.get("availBal", 0))
        return 0.0
    except Exception as e:
        log(f"Balance error: {e}")
        return 0.0

def get_all_spot_tickers():
    try:
        path = "/api/v5/market/tickers?instType=SPOT"
        r = requests.get(BASE_URL + path, timeout=15)
        return r.json().get("data", [])
    except:
        return []

def get_candles(symbol, bar="1H", limit=24):
    try:
        path = f"/api/v5/market/candles?instId={symbol}&bar={bar}&limit={limit}"
        r = requests.get(BASE_URL + path, timeout=10)
        candles = r.json().get("data", [])
        return [float(c[4]) for c in reversed(candles)]
    except:
        return []

def get_price(symbol):
    try:
        path = f"/api/v5/market/ticker?instId={symbol}"
        r = requests.get(BASE_URL + path, timeout=10)
        return float(r.json().get("data", [{}])[0].get("last", 0))
    except:
        return 0.0

def calculate_volatility(closes):
    if len(closes) < 4:
        return 0
    changes = [abs(closes[i] - closes[i-1]) / closes[i-1] * 100
               for i in range(1, len(closes))]
    return sum(changes) / len(changes)

def scan_best_coin():
    log("🔍 Inascan coins za OKX Spot...")
    tickers = get_all_spot_tickers()
    candidates = []

    for t in tickers:
        inst_id = t.get("instId", "")
        if not inst_id.endswith("-USDT"):
            continue
        base = inst_id.replace("-USDT", "")
        if any(bl in base for bl in BLACKLIST):
            continue
        price = float(t.get("last", 0))
        if price < MIN_PRICE or price > MAX_PRICE:
            continue
        vol = float(t.get("volCcy24h", 0))
        vol_usd = vol * price
        if vol_usd < MIN_VOLUME_USD:
            continue
        sod = float(t.get("sodUtc8", price))
        change_pct = abs((price - sod) / sod * 100) if sod > 0 else 0
        if change_pct < MIN_CHANGE_PCT or change_pct > MAX_CHANGE_PCT:
            continue
        candidates.append({
            "instId": inst_id,
            "price": price,
            "vol_usd": vol_usd,
            "change_pct": round(change_pct, 2)
        })

    log(f"Candidates waliopatikana: {len(candidates)}")

    candidates.sort(key=lambda x: x["vol_usd"], reverse=True)

    best = None
    best_score = 0

    for coin in candidates[:20]:
        closes = get_candles(coin["instId"])
        if len(closes) < 4:
            continue
        volatility = calculate_volatility(closes)
        if volatility < 0.1:
            continue
        min_p = min(closes[-12:]) if len(closes) >= 12 else min(closes)
        max_p = max(closes[-12:]) if len(closes) >= 12 else max(closes)
        range_pct = (max_p - min_p) / min_p * 100 if min_p > 0 else 0
        score = (volatility * 0.4) + (range_pct * 0.3) + (coin["vol_usd"] / 1_000_000 * 0.3)
        if score > best_score:
            best_score = score
            best = coin
            best["volatility"] = round(volatility, 2)
            best["range_pct"] = round(range_pct, 2)
        time.sleep(0.1)

    return best

def place_order(symbol, side, price, size):
    if DRY_RUN:
        log(f"[SIM] {side} {size:.4f} @ ${price:.6f}")
        return {"ordId": "sim123"}
    try:
        path = "/api/v5/trade/order"
        body = json.dumps({
            "instId": symbol,
            "tdMode": "cash",
            "side": side.lower(),
            "ordType": "limit",
            "px": str(round(price, 6)),
            "sz": str(round(size, 4)),
        })
        headers = get_headers("POST", path, body)
        r = requests.post(BASE_URL + path, headers=headers, data=body, timeout=10)
        data = r.json()
        if data.get("code") == "0":
            return data.get("data", [{}])[0]
        else:
            log(f"Order failed: {data.get('msg')}")
            return None
    except Exception as e:
        log(f"Order error: {e}")
        return None

def calculate_grids(current_price):
    grids = []
    half = GRID_COUNT // 2
    for i in range(-half, half + 1):
        if i == 0:
            continue
        price = current_price * (1 + i * GRID_SPREAD)
        side = "BUY" if i < 0 else "SELL"
        grids.append({"price": round(price, 6), "side": side})
    return grids

def needs_rebalance(current_price, active_orders):
    buy_prices = [o["price"] for o in active_orders if o["side"] == "BUY" and not o["filled"]]
    sell_prices = [o["price"] for o in active_orders if o["side"] == "SELL" and not o["filled"]]
    if not buy_prices or not sell_prices:
        return True
    if current_price > min(sell_prices) * (1 + REBALANCE_THRESHOLD):
        return True
    if current_price < max(buy_prices) * (1 - REBALANCE_THRESHOLD):
        return True
    return False

def format_grid_report(active_orders, current_price):
    buy_orders = sorted([o for o in active_orders if o["side"] == "BUY" and not o["filled"]],
                        key=lambda x: x["price"], reverse=True)
    sell_orders = sorted([o for o in active_orders if o["side"] == "SELL" and not o["filled"]],
                         key=lambda x: x["price"])
    lines = [f"💲 Bei sasa: ${current_price:.6f}\n"]
    lines.append("🔴 SELL (zinangoja kupanda):")
    for o in sell_orders:
        lines.append(f"  └ ${o['price']:.6f} | {o['qty']:.4f}")
    lines.append("")
    lines.append("🟢 BUY (zinangoja kushuka):")
    for o in buy_orders:
        lines.append(f"  └ ${o['price']:.6f} | {o['qty']:.4f}")
    return "\n".join(lines)

def run_grid_bot():
    global total_pnl, trade_count, current_symbol, initial_balance

    balance = get_balance()
    initial_balance = balance

    if balance < 1.0:
        msg = f"❌ Balance ndogo: ${balance:.4f}\nHitaji angalau $1 USDT!"
        log(msg)
        send_telegram(msg)
        return

    capital = round(balance * 0.95, 4)

    send_telegram(
        f"🤖 OKX SMART GRID BOT!\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 Balance: ${balance:.4f} USDT\n"
        f"💵 Capital: ${capital:.4f} USDT\n"
        f"🔢 Grids: {GRID_COUNT} | Spread: {GRID_SPREAD*100:.1f}%\n"
        f"🔴 Mode: LIVE\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔍 Inascan coin nzuri..."
    )

    last_scan = 0
    active_orders = []
    filled_buys = []
    current_price = 0

    while True:
        try:
            now = time.time()

            if now - last_scan > SCAN_INTERVAL or not current_symbol:
                coin = scan_best_coin()

                if not coin:
                    log("Hakuna coin — inatumia DOGE-USDT kama default...")
                    coin = {
                        "instId": "DOGE-USDT",
                        "price": get_price("DOGE-USDT"),
                        "vol_usd": 0,
                        "change_pct": 0,
                        "volatility": 0,
                        "range_pct": 0
                    }

                new_symbol = coin["instId"]

                if new_symbol != current_symbol:
                    current_symbol = new_symbol
                    active_orders = []
                    filled_buys = []

                    price = get_price(current_symbol)
                    grids = calculate_grids(price)
                    amount_per_grid = capital / (GRID_COUNT / 2)

                    for g in grids:
                        qty = amount_per_grid / g["price"]
                        active_orders.append({**g, "qty": qty, "filled": False})

                    grid_report = format_grid_report(active_orders, price)

                    send_telegram(
                        f"🎯 COIN IMECHAGULIWA!\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"📊 {current_symbol}\n"
                        f"📈 Volatility: {coin.get('volatility', 0)}%\n"
                        f"📊 Range 12h: {coin.get('range_pct', 0)}%\n"
                        f"💧 Volume: ${coin['vol_usd']/1_000_000:.2f}M\n"
                        f"━━━━━━━━━━━━━━━\n"
                        f"{grid_report}"
                    )

                last_scan = now

            current_price = get_price(current_symbol)
            if not current_price:
                time.sleep(CHECK_INTERVAL)
                continue

            if needs_rebalance(current_price, active_orders):
                balance_now = get_balance()
                balance_change = balance_now - initial_balance
                grids = calculate_grids(current_price)
                amount_per_grid = capital / (GRID_COUNT / 2)
                active_orders = []
                for g in grids:
                    qty = amount_per_grid / g["price"]
                    active_orders.append({**g, "qty": qty, "filled": False})
                filled_buys = []
                grid_report = format_grid_report(active_orders, current_price)
                send_telegram(
                    f"🔄 GRIDS ZIMESASAHISHWA!\n"
                    f"📊 {current_symbol}\n"
                    f"💰 Balance: ${balance_now:.4f} USDT\n"
                    f"{'📈' if balance_change >= 0 else '📉'} Mabadiliko: {'+' if balance_change >= 0 else ''}{balance_change:.4f}\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"{grid_report}"
                )
                time.sleep(CHECK_INTERVAL)
                continue

            for order in active_orders:
                if order["filled"]:
                    continue

                if order["side"] == "BUY" and current_price <= order["price"]:
                    result = place_order(current_symbol, "BUY", order["price"], order["qty"])
                    if result:
                        order["filled"] = True
                        filled_buys.append(order.copy())
                        trade_count += 1
                        balance_now = get_balance()
                        balance_change = balance_now - initial_balance
                        pending_sells = sorted(
                            [o for o in active_orders if o["side"] == "SELL" and not o["filled"]],
                            key=lambda x: x["price"]
                        )
                        sell_targets = " | ".join([f"${o['price']:.6f}" for o in pending_sells[:3]])
                        send_telegram(
                            f"🟢 BUY #{trade_count} IMEFANYIKA!\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"📊 {current_symbol}\n"
                            f"💲 Imenunua @ ${order['price']:.6f}\n"
                            f"📦 Kiasi: {order['qty']:.4f}\n"
                            f"🎯 Sell targets: {sell_targets}\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"💰 Balance: ${balance_now:.4f} USDT\n"
                            f"{'📈' if balance_change >= 0 else '📉'} Mabadiliko: {'+' if balance_change >= 0 else ''}{balance_change:.4f}\n"
                            f"🔴 LIVE"
                        )

                elif order["side"] == "SELL" and current_price >= order["price"]:
                    match = next((b for b in filled_buys if not b.get("sold")), None)
                    if match:
                        result = place_order(current_symbol, "SELL", order["price"], order["qty"])
                        if result:
                            order["filled"] = True
                            match["sold"] = True
                            pnl = (order["price"] - match["price"]) * order["qty"]
                            total_pnl += pnl
                            trade_count += 1
                            balance_now = get_balance()
                            balance_change = balance_now - initial_balance
                            send_telegram(
                                f"🔴 SELL #{trade_count} IMEFANYIKA!\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"📊 {current_symbol}\n"
                                f"💲 Ilinunua @ ${match['price']:.6f}\n"
                                f"💲 Imeuza @ ${order['price']:.6f}\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"💰 PnL: +${pnl:.4f} USDT\n"
                                f"📈 Jumla PnL: ${total_pnl:.4f} USDT\n"
                                f"━━━━━━━━━━━━━━━\n"
                                f"💵 Balance: ${balance_now:.4f} USDT\n"
                                f"📊 Mwanzo: ${initial_balance:.4f} USDT\n"
                                f"{'📈' if balance_change >= 0 else '📉'} Mabadiliko: {'+' if balance_change >= 0 else ''}{balance_change:.4f} USDT\n"
                                f"🔴 LIVE"
                            )

            all_filled = all(o["filled"] for o in active_orders)
            if all_filled:
                balance_now = get_balance()
                balance_change = balance_now - initial_balance
                send_telegram(
                    f"🔄 Grids zote zimefanyika!\n"
                    f"📈 Jumla PnL: ${total_pnl:.4f}\n"
                    f"💵 Balance: ${balance_now:.4f} USDT\n"
                    f"{'📈' if balance_change >= 0 else '📉'} Mabadiliko: {'+' if balance_change >= 0 else ''}{balance_change:.4f}\n"
                    f"🔁 Inaanza upya..."
                )
                grids = calculate_grids(current_price)
                active_orders = []
                for g in grids:
                    qty = capital / (GRID_COUNT / 2) / g["price"]
                    active_orders.append({**g, "qty": qty, "filled": False})
                filled_buys = []

            time.sleep(CHECK_INTERVAL)

        except KeyboardInterrupt:
            balance_now = get_balance()
            send_telegram(
                f"🛑 Bot imesimamishwa!\n"
                f"📈 Jumla PnL: ${total_pnl:.4f}\n"
                f"💵 Balance ya mwisho: ${balance_now:.4f} USDT"
            )
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_grid_bot()

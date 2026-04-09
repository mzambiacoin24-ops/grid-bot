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

SYMBOL = "XRP-USDT"
GRID_COUNT = 10
GRID_SPREAD = 0.003
DRY_RUN = False

BASE_URL = "https://www.okx.com"

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
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    message = timestamp + method.upper() + path + body
    signature = base64.b64encode(
        hmac.new(
            OKX_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
    ).decode()
    return {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type": "application/json"
    }

def get_usdt_balance():
    try:
        path = "/api/v5/account/balance?ccy=USDT"
        headers = get_headers("GET", path)
        r = requests.get(BASE_URL + path, headers=headers, timeout=10)
        data = r.json()
        details = data.get("data", [{}])[0].get("details", [])
        for d in details:
            if d.get("ccy") == "USDT":
                balance = float(d.get("availBal", 0))
                log(f"Balance ya USDT: ${balance:.4f}")
                return balance
        return 0.0
    except Exception as e:
        log(f"Balance error: {e}")
        return 0.0

def get_price():
    try:
        path = f"/api/v5/market/ticker?instId={SYMBOL}"
        r = requests.get(BASE_URL + path, timeout=10)
        data = r.json()
        price = float(data.get("data", [{}])[0].get("last", 0))
        return price
    except Exception as e:
        log(f"Price error: {e}")
        return None

def place_order(side, price, size):
    if DRY_RUN:
        log(f"[SIM] {side} {size:.4f} XRP @ ${price:.4f}")
        return {"ordId": "sim123"}
    try:
        path = "/api/v5/trade/order"
        body = json.dumps({
            "instId": SYMBOL,
            "tdMode": "cash",
            "side": side.lower(),
            "ordType": "limit",
            "px": str(round(price, 4)),
            "sz": str(round(size, 4)),
        })
        headers = get_headers("POST", path, body)
        r = requests.post(BASE_URL + path, headers=headers, data=body, timeout=10)
        data = r.json()
        result = data.get("data", [{}])[0]
        if data.get("code") == "0":
            return result
        else:
            log(f"Order failed: {data.get('msg')} | {result.get('sMsg')}")
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
        grids.append({"price": round(price, 4), "side": side})
    return grids

def run_grid_bot():
    balance = get_usdt_balance()

    if balance < 1.0:
        msg = f"❌ Balance ndogo sana: ${balance:.4f}\nHitaji angalau $1 USDT!"
        log(msg)
        send_telegram(msg)
        return

    capital = round(balance * 0.95, 4)

    mode = "🔴 LIVE" if not DRY_RUN else "🧪 SIMULATION"

    msg = (
        f"🤖 OKX XRP Grid Bot Inaanza!\n"
        f"💰 Balance: ${balance:.4f} USDT\n"
        f"💵 Capital: ${capital:.4f} USDT\n"
        f"📊 Symbol: {SYMBOL}\n"
        f"🔢 Grids: {GRID_COUNT}\n"
        f"📏 Spread: {GRID_SPREAD*100}%\n"
        f"⚡ Mode: {mode}"
    )
    log(msg)
    send_telegram(msg)

    price = get_price()
    if not price:
        msg = "❌ Imeshindwa kupata price!"
        log(msg)
        send_telegram(msg)
        return

    msg = f"💲 XRP Bei ya sasa: ${price:.4f}"
    log(msg)
    send_telegram(msg)

    grids = calculate_grids(price)
    amount_per_grid = capital / (GRID_COUNT / 2)

    active_orders = []
    grid_lines = []
    for g in grids:
        qty = amount_per_grid / g["price"]
        active_orders.append({**g, "qty": qty, "filled": False})
        emoji = "🟢" if g["side"] == "BUY" else "🔴"
        grid_lines.append(f"{emoji} {g['side']} @ ${g['price']:.4f}")

    grid_msg = "📋 Grid Levels:\n" + "\n".join(grid_lines)
    log(grid_msg)
    send_telegram(grid_msg)
    send_telegram("👀 Bot inaangalia market...")

    filled_buys = []
    total_pnl = 0.0
    trade_count = 0
    error_count = 0

    # ✅ START WITH BUY
    initial_qty = (capital * 0.2) / price
    buy_result = place_order("BUY", price, initial_qty)
    if buy_result:
        msg = f"🚀 START BUY\n💲 Bei: ${price:.4f}\n📦 XRP: {initial_qty:.4f}"
        log(msg)
        send_telegram(msg)
        filled_buys.append({
            "price": price,
            "qty": initial_qty,
            "filled": True,
            "sold": False
        })

    grid_top = max(g["price"] for g in grids)

    while True:
        try:
            current_price = get_price()
            if not current_price:
                error_count += 1
                time.sleep(5)
                continue

            error_count = 0

            # ✅ AUTO RESET GRID
            if current_price > grid_top:
                msg = f"🔄 RESET GRID\nPrice: ${current_price:.4f}"
                log(msg)
                send_telegram(msg)

                price = current_price
                grids = calculate_grids(price)

                active_orders = []
                for g in grids:
                    qty = amount_per_grid / g["price"]
                    active_orders.append({**g, "qty": qty, "filled": False})

                grid_top = max(g["price"] for g in grids)
                continue

            for order in active_orders:
                if order["filled"]:
                    continue

                if order["side"] == "BUY" and current_price <= order["price"]:
                    result = place_order("BUY", order["price"], order["qty"])
                    if result:
                        order["filled"] = True
                        filled_buys.append(order.copy())
                        trade_count += 1
                        msg = f"🟢 BUY #{trade_count}\n💲 {order['price']:.4f}"
                        log(msg)
                        send_telegram(msg)

                elif order["side"] == "SELL" and current_price >= order["price"]:
                    matching_buy = next((b for b in filled_buys if not b.get("sold")), None)
                    if matching_buy:
                        result = place_order("SELL", order["price"], order["qty"])
                        if result:
                            order["filled"] = True
                            matching_buy["sold"] = True
                            pnl = (order["price"] - matching_buy["price"]) * order["qty"]
                            total_pnl += pnl
                            trade_count += 1
                            msg = f"🔴 SELL #{trade_count}\n💰 +${pnl:.4f}"
                            log(msg)
                            send_telegram(msg)

            time.sleep(5)

        except Exception as e:
            log(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_grid_bot()

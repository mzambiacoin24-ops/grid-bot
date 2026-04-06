import time
import hmac
import hashlib
import base64
import json
import requests
from datetime import datetime

KUCOIN_API_KEY = "69d36930d5d5ab0001a2e3be"
KUCOIN_API_SECRET = "fd52e48e-39b1-4704-bc75-537b800d9e3c"
KUCOIN_PASSPHRASE = "gridbot2026"

TELEGRAM_TOKEN = "8632951293:AAF1hhp3hz-ZjgJwaMmfAozEgbpxK9yCsNo"
TELEGRAM_CHAT_ID = "7010983039"

SYMBOL = "XRP-USDT"
CAPITAL = 30
GRID_COUNT = 10
GRID_SPREAD = 0.015
DRY_RUN = True

BASE_URL = "https://api.kucoin.com"

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        log(f"Telegram error: {e}")

def get_headers(method, endpoint, body=""):
    timestamp = str(int(time.time() * 1000))
    str_to_sign = timestamp + method.upper() + endpoint + body
    signature = base64.b64encode(
        hmac.new(
            KUCOIN_API_SECRET.encode(),
            str_to_sign.encode(),
            hashlib.sha256
        ).digest()
    ).decode()
    passphrase = base64.b64encode(
        hmac.new(
            KUCOIN_API_SECRET.encode(),
            KUCOIN_PASSPHRASE.encode(),
            hashlib.sha256
        ).digest()
    ).decode()
    return {
        "KC-API-KEY": KUCOIN_API_KEY,
        "KC-API-SIGN": signature,
        "KC-API-TIMESTAMP": timestamp,
        "KC-API-PASSPHRASE": passphrase,
        "KC-API-KEY-VERSION": "2",
        "Content-Type": "application/json"
    }

def get_price():
    try:
        url = f"{BASE_URL}/api/v1/market/orderbook/level1?symbol={SYMBOL}"
        r = requests.get(url, timeout=10)
        data = r.json()
        return float(data["data"]["price"])
    except Exception as e:
        log(f"Error kupata price: {e}")
        return None

def place_order(side, price, size):
    if DRY_RUN:
        log(f"[SIMULATION] {side} {size:.2f} XRP @ ${price:.4f}")
        return {"orderId": "sim123"}
    try:
        endpoint = "/api/v1/orders"
        body = json.dumps({
            "clientOid": str(int(time.time() * 1000)),
            "side": side.lower(),
            "symbol": SYMBOL,
            "type": "limit",
            "price": str(round(price, 4)),
            "size": str(round(size, 2)),
        })
        headers = get_headers("POST", endpoint, body)
        r = requests.post(BASE_URL + endpoint, headers=headers, data=body, timeout=10)
        return r.json().get("data")
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
    msg = (
        f"🤖 KuCoin Grid Bot Inaanza!\n"
        f"💰 Capital: ${CAPITAL}\n"
        f"📊 Symbol: {SYMBOL}\n"
        f"🔢 Grids: {GRID_COUNT}\n"
        f"🧪 Mode: {'SIMULATION' if DRY_RUN else 'LIVE'}"
    )
    log(msg)
    send_telegram(msg)

    price = get_price()
    if not price:
        msg = "❌ Imeshindwa kupata price. Bot inasimama!"
        log(msg)
        send_telegram(msg)
        return

    msg = f"💲 XRP Price ya sasa: ${price:.4f}"
    log(msg)
    send_telegram(msg)

    grids = calculate_grids(price)
    amount_per_grid = CAPITAL / (GRID_COUNT / 2)

    active_orders = []
    for g in grids:
        qty = amount_per_grid / g["price"]
        active_orders.append({**g, "qty": qty, "filled": False})

    send_telegram(f"📋 Grids {GRID_COUNT} zimeandaliwa. Bot inaangalia market...")

    filled_buys = []
    total_pnl = 0.0
    error_count = 0

    while True:
        try:
            current_price = get_price()
            if not current_price:
                error_count += 1
                if error_count >= 5:
                    send_telegram("⚠️ Imeshindwa kupata bei mara 5. Inaendelea kujaribu...")
                    error_count = 0
                time.sleep(15)
                continue

            error_count = 0

            for order in active_orders:
                if order["filled"]:
                    continue

                if order["side"] == "BUY" and current_price <= order["price"]:
                    result = place_order("BUY", order["price"], order["qty"])
                    if result:
                        order["filled"] = True
                        filled_buys.append(order.copy())
                        msg = (
                            f"🟢 BUY imefanyika!\n"
                            f"💲 Bei: ${order['price']:.4f}\n"
                            f"📦 Kiasi: {order['qty']:.2f} XRP\n"
                            f"🧪 SIMULATION"
                        )
                        log(msg)
                        send_telegram(msg)

                elif order["side"] == "SELL" and current_price >= order["price"]:
                    matching_buy = next(
                        (b for b in filled_buys if not b.get("sold")), None
                    )
                    if matching_buy:
                        result = place_order("SELL", order["price"], order["qty"])
                        if result:
                            order["filled"] = True
                            matching_buy["sold"] = True
                            pnl = (order["price"] - matching_buy["price"]) * order["qty"]
                            total_pnl += pnl
                            msg = (
                                f"🔴 SELL imefanyika!\n"
                                f"💲 Bei: ${order['price']:.4f}\n"
                                f"📦 Kiasi: {order['qty']:.2f} XRP\n"
                                f"💰 PnL: +${pnl:.4f}\n"
                                f"📈 Total PnL: ${total_pnl:.4f}\n"
                                f"🧪 SIMULATION"
                            )
                            log(msg)
                            send_telegram(msg)

            all_filled = all(o["filled"] for o in active_orders)
            if all_filled:
                msg = f"🔄 Grids zote zimefanyika! Inaanza upya...\n📈 Total PnL: ${total_pnl:.4f}"
                log(msg)
                send_telegram(msg)
                grids = calculate_grids(current_price)
                active_orders = []
                for g in grids:
                    qty = amount_per_grid / g["price"]
                    active_orders.append({**g, "qty": qty, "filled": False})
                filled_buys = []

            time.sleep(15)

        except KeyboardInterrupt:
            msg = f"🛑 Bot imesimamishwa.\n📈 Total PnL: ${total_pnl:.4f}"
            log(msg)
            send_telegram(msg)
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(15)

if __name__ == "__main__":
    run_grid_bot()

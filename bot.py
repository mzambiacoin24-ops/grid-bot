import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime

API_KEY = os.environ.get("BINANCE_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

TELEGRAM_TOKEN = "8632951293:AAF1hhp3hz-ZjgJwaMmfAozEgbpxK9yCsNo"
TELEGRAM_CHAT_ID = "7010983039"

SYMBOL = "SOLUSDT"
CAPITAL = 30
GRID_COUNT = 10
GRID_SPREAD = 0.015
DRY_RUN = True

BASE_URL = "https://api.binance.com"

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def get_signature(params, secret):
    query = urlencode(params)
    return hmac.new(
        secret.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

def get_price(symbol):
    try:
        url = f"{BASE_URL}/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url, timeout=10)
        return float(r.json()["price"])
    except Exception as e:
        log(f"Error kupata price: {e}")
        return None

def get_balance():
    if DRY_RUN:
        return {"USDT": CAPITAL, "SOL": 0.0}
    try:
        params = {"timestamp": int(time.time() * 1000)}
        params["signature"] = get_signature(params, API_SECRET)
        headers = {"X-MBX-APIKEY": API_KEY}
        url = f"{BASE_URL}/api/v3/account"
        r = requests.get(url, headers=headers, params=params)
        balances = r.json().get("balances", [])
        result = {}
        for b in balances:
            if b["asset"] in ["USDT", "SOL"]:
                result[b["asset"]] = float(b["free"])
        return result
    except Exception as e:
        log(f"Error kupata balance: {e}")
        return None

def place_order(side, price, quantity):
    if DRY_RUN:
        log(f"[SIMULATION] {side} {quantity:.4f} SOL @ ${price:.2f}")
        return {"status": "FILLED", "price": price, "qty": quantity}
    try:
        params = {
            "symbol": SYMBOL,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": round(quantity, 2),
            "price": round(price, 2),
            "timestamp": int(time.time() * 1000)
        }
        params["signature"] = get_signature(params, API_SECRET)
        headers = {"X-MBX-APIKEY": API_KEY}
        url = f"{BASE_URL}/api/v3/order"
        r = requests.post(url, headers=headers, params=params)
        return r.json()
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
        grids.append({
            "price": round(price, 4),
            "side": side,
            "level": i
        })
    return grids

def run_grid_bot():
    msg = (
        "🤖 Grid Bot Inaanza!\n"
        f"💰 Capital: ${CAPITAL}\n"
        f"📊 Symbol: {SYMBOL}\n"
        f"🔢 Grids: {GRID_COUNT}\n"
        f"🧪 Mode: {'SIMULATION' if DRY_RUN else 'LIVE'}"
    )
    log(msg)
    send_telegram(msg)

    price = get_price(SYMBOL)
    if not price:
        log("Imeshindwa kupata price. Bot inasimama.")
        send_telegram("❌ Bot imeshindwa kupata price. Imesimama!")
        return

    start_msg = f"💲 SOL Price ya sasa: ${price:.2f}"
    log(start_msg)
    send_telegram(start_msg)

    grids = calculate_grids(price)
    amount_per_grid = CAPITAL / (GRID_COUNT / 2)

    active_orders = []
    for g in grids:
        qty = amount_per_grid / g["price"]
        active_orders.append({**g, "qty": qty, "filled": False})

    send_telegram(f"📋 Grids {GRID_COUNT} zimeandaliwa. Bot inaangalia market...")

    filled_buys = []
    total_pnl = 0.0

    while True:
        try:
            current_price = get_price(SYMBOL)
            if not current_price:
                time.sleep(5)
                continue

            for order in active_orders:
                if order["filled"]:
                    continue

                if order["side"] == "BUY" and current_price <= order["price"]:
                    result = place_order("BUY", order["price"], order["qty"])
                    if result:
                        order["filled"] = True
                        filled_buys.append(order)
                        msg = (
                            f"🟢 BUY imefanyika!\n"
                            f"💲 Bei: ${order['price']:.4f}\n"
                            f"📦 Kiasi: {order['qty']:.4f} SOL\n"
                            f"🧪 SIMULATION"
                        )
                        log(msg)
                        send_telegram(msg)

                elif order["side"] == "SELL" and current_price >= order["price"]:
                    matching_buy = next(
                        (b for b in filled_buys if not b.get("sold")),
                        None
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
                                f"📦 Kiasi: {order['qty']:.4f} SOL\n"
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

            time.sleep(10)

        except KeyboardInterrupt:
            msg = f"🛑 Bot imesimamishwa.\n📈 Total PnL: ${total_pnl:.4f}"
            log(msg)
            send_telegram(msg)
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_grid_bot()

import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import json
from dotenv import load_dotenv

MAX_GBP_PER_TRADE = 5.0
PROFIT_TARGET = 0.1
STOP_LOSS = 0.5
CHECK_INTERVAL = 30

API_URL = "https://api.kraken.com"
POSITIONS_FILE = os.path.expanduser("~/positions.json")

load_dotenv(os.path.expanduser("~/.env"))
API_KEY = os.getenv("KRAKEN_API_KEY", "")
API_SECRET = os.getenv("KRAKEN_API_SECRET", "")

TRADE_PAIRS = [
    "XBTGBP",
    "XETHGBP",
    "SOLGBP",
    "XDGGBP"
]

def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f)

def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, "r") as f:
            return json.load(f)
    return {pair: None for pair in TRADE_PAIRS}

current_position = load_positions()

def kraken_sign(path, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()

def private_request(path, data=None):
    data = data or {}
    if not API_KEY or not API_SECRET:
        raise RuntimeError("Missing API keys in .env file")
    data["nonce"] = int(time.time() * 1000)
    headers = {
        "API-Key": API_KEY,
        "API-Sign": kraken_sign(path, data, API_SECRET)
    }
    try:
        resp = requests.post(API_URL + path, data=data, headers=headers, timeout=30).json()
        if resp.get("error"):
            print(f"API ERROR: {resp['error']}")
        return resp
    except Exception as e:
        print(f"CONNECTION ERROR: {e}")
        return {}

def get_price(pair):
    try:
        r = requests.get(f"{API_URL}/0/public/Ticker", params={"pair": pair}, timeout=10).json()
        if "result" in r:
            key = next(iter(r["result"]))
            return float(r["result"][key]["c"][0])
        return None
    except:
        return None

def get_min_volume(pair):
    mins = {
        "XBTGBP": 0.0001,
        "XETHGBP": 0.01,
        "SOLGBP": 0.5,
        "XDGGBP": 50.0
    }
    return mins.get(pair, 1.0)

def place_order(side, pair, volume):
    min_vol = get_min_volume(pair)
    if volume < min_vol:
        volume = min_vol
    print(f"ORDER: {side.upper()} {volume:.6f} {pair}")
    data = {
        "pair": pair,
        "type": side,
        "ordertype": "market",
        "volume": f"{volume:.6f}"
    }
    return private_request("/0/private/AddOrder", data)

def main():
    print("="*60)
    print("CRYPTO BOT RUNNING")
    print(f"Profit target: {PROFIT_TARGET}% | Stop loss: {STOP_LOSS}%")
    print(f"Per trade: GBP{MAX_GBP_PER_TRADE} | Interval: {CHECK_INTERVAL}s")
    print("="*60)

    try:
        bal = private_request("/0/private/Balance")
        if "result" in bal:
            gbp_bal = float(bal["result"].get("ZGBP", 0))
            print(f"Balance: GBP{gbp_bal:.2f}")
    except:
        print("Balance check skipped")

    for pair in TRADE_PAIRS:
        price = get_price(pair)
        if not price:
            print(f"Could not get price for {pair}, skipping")
            time.sleep(2)
            continue

        print(f"{pair}: GBP{price:.4f}")

        if current_position[pair] is None:
            volume = MAX_GBP_PER_TRADE / price
            min_vol = get_min_volume(pair)
            if volume < min_vol:
                volume = min_vol
            res = place_order("buy", pair, volume)
            if not res.get("error"):
                current_position[pair] = {"price": price, "volume": volume}
                save_positions(current_position)
                print(f"BOUGHT {pair} at GBP{price:.4f} vol:{volume:.6f}")

        else:
            entry = current_position[pair]["price"]
            volume = current_position[pair]["volume"]
            take_profit = entry * (1 + PROFIT_TARGET / 100)
            stop_loss = entry * (1 - STOP_LOSS / 100)
            print(f"{pair} | entry:GBP{entry:.4f} | TP:GBP{take_profit:.4f} | SL:GBP{stop_loss:.4f} | now:GBP{price:.4f}")

            if price >= take_profit:
                res = place_order("sell", pair, volume)
                if not res.get("error"):
                    profit = (price - entry) / entry * MAX_GBP_PER_TRADE
                    current_position[pair] = None
                    save_positions(current_position)
                    print(f"PROFIT TAKEN: {pair} +GBP{profit:.4f}")

            elif price <= stop_loss:
                res = place_order("sell", pair, volume)
                if not res.get("error"):
                    loss = (entry - price) / entry * MAX_GBP_PER_TRADE
                    current_position[pair] = None
                    save_positions(current_position)
                    print(f"STOP LOSS: {pair} -GBP{loss:.4f}")

        time.sleep(2)

if __name__ == "__main__":
    while True:
        main()
        time.sleep(CHECK_INTERVAL)

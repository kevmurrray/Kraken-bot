import time
import requests
import os
import json
import hmac
import hashlib
import base64
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"))
API_KEY = os.getenv("KRAKEN_API_KEY", "")
API_SECRET = os.getenv("KRAKEN_API_SECRET", "")

API_URL = "https://api.kraken.com"
POSITIONS_FILE = os.path.expanduser("~/sentiment_positions.json")
LOG_FILE = os.path.expanduser("~/sentiment_bot.log")

STAKE_GBP = 5.0
PAIRS = {
    "bitcoin": {"kraken": "XBTGBP", "min_vol": 0.0001},
    "ethereum": {"kraken": "XETHGBP", "min_vol": 0.01},
    "solana": {"kraken": "SOLGBP", "min_vol": 0.5}
}

BUY_THRESHOLD = 35
SELL_THRESHOLD = 70
CHECK_INTERVAL = 3600
PAPER_TRADING = True

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def get_fear_greed():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10).json()
        score = int(r["data"][0]["value"])
        label = r["data"][0]["value_classification"]
        return score, label
    except Exception as e:
        log(f"Fear/Greed error: {e}")
        return None, None

def get_prices():
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum,solana", "vs_currencies": "gbp", "include_24hr_change": "true"},
            timeout=10
        ).json()
        return r
    except Exception as e:
        log(f"Price error: {e}")
        return None

def save_positions(positions):
    with open(POSITIONS_FILE, "w") as f:
        json.dump(positions, f)

def load_positions():
    if os.path.exists(POSITIONS_FILE):
        with open(POSITIONS_FILE, "r") as f:
            return json.load(f)
    return {}

def kraken_sign(path, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()

def private_request(path, data=None):
    data = data or {}
    data["nonce"] = int(time.time() * 1000)
    headers = {
        "API-Key": API_KEY,
        "API-Sign": kraken_sign(path, data, API_SECRET)
    }
    try:
        resp = requests.post(API_URL + path, data=data, headers=headers, timeout=30).json()
        if resp.get("error"):
            log(f"API ERROR: {resp['error']}")
        return resp
    except Exception as e:
        log(f"Connection error: {e}")
        return {}

def place_order(side, pair, volume):
    if PAPER_TRADING:
        log(f"[PAPER] Would {side.upper()} {volume:.6f} {pair}")
        return {"paper": True}
    log(f"ORDER: {side.upper()} {volume:.6f} {pair}")
    data = {
        "pair": pair,
        "type": side,
        "ordertype": "market",
        "volume": f"{volume:.6f}"
    }
    return private_request("/0/private/AddOrder", data)

def get_balance():
    bal = private_request("/0/private/Balance")
    if "result" in bal:
        return float(bal["result"].get("ZGBP", 0))
    return 0

def run():
    positions = load_positions()
    mode = "PAPER" if PAPER_TRADING else "LIVE"
    log("=" * 50)
    log(f"SENTIMENT BOT STARTED -- {mode} MODE")
    log("=" * 50)

    while True:
        try:
            score, label = get_fear_greed()
            prices = get_prices()

            if score is None or prices is None:
                log("Could not get data, retrying in 10 minutes")
                time.sleep(600)
                continue

            balance = get_balance()
            log(f"Fear & Greed: {score} ({label})")
            log(f"Balance: GBP{balance:.2f}")

            for coin, info in PAIRS.items():
                if coin not in prices:
                    continue

                price_gbp = prices[coin]["gbp"]
                change_24h = prices[coin]["gbp_24h_change"]
                kraken_pair = info["kraken"]
                min_vol = info["min_vol"]

                log(f"{coin.upper()}: GBP{price_gbp:.2f} ({change_24h:+.2f}%)")

                if score <= BUY_THRESHOLD and coin not in positions:
                    if change_24h > -5:
                        volume = max(STAKE_GBP / price_gbp, min_vol)
                        log(f"SIGNAL: BUY {coin} - Fear score {score}, price not crashing")
                        place_order("buy", kraken_pair, volume)
                        positions[coin] = {"price": price_gbp, "volume": volume}
                        save_positions(positions)

                elif score >= SELL_THRESHOLD and coin in positions:
                    entry = positions[coin]["price"]
                    volume = positions[coin]["volume"]
                    profit_pct = (price_gbp - entry) / entry * 100
                    log(f"SIGNAL: SELL {coin} - Greed score {score}, profit {profit_pct:+.2f}%")
                    place_order("sell", kraken_pair, volume)
                    del positions[coin]
                    save_positions(positions)

                elif coin in positions:
                    entry = positions[coin]["price"]
                    profit_pct = (price_gbp - entry) / entry * 100
                    stop_loss_price = entry * 0.92
                    if price_gbp <= stop_loss_price:
                        log(f"STOP LOSS: {coin} dropped 8% from entry")
                        volume = positions[coin]["volume"]
                        place_order("sell", kraken_pair, volume)
                        del positions[coin]
                        save_positions(positions)
                    else:
                        log(f"HOLDING {coin}: entry GBP{entry:.2f}, now GBP{price_gbp:.2f}, P&L {profit_pct:+.2f}%")

            log(f"Next check in {CHECK_INTERVAL//3600} hour(s)")
            log("-" * 50)
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            log(f"Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run()

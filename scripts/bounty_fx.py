"""Actual observed currency quotes; missing quotes never become invented USD."""
import json
import time
from urllib.request import Request, urlopen

from actions_github import utcnow

_cache = {}


def quote(currency):
    cached = _cache.get(currency)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]
    if currency in ("ETH", "SOL"):
        url = f"https://api.coinbase.com/v2/prices/{currency}-USD/spot"
    else:
        url = f"https://api.frankfurter.dev/v1/latest?base={currency}&symbols=USD"
    with urlopen(Request(url, headers={"User-Agent": "bounty-admission"}), timeout=20) as response:
        payload = json.load(response)
    rate = payload["data"]["amount"] if currency in ("ETH", "SOL") else payload["rates"]["USD"]
    result = {"usd_rate": str(rate), "source_url": url, "observed_at": utcnow(),
              "quote_date": payload.get("date")}
    _cache[currency] = (time.monotonic(), result)
    return result

import os
import time
from datetime import datetime, time as dtime
import pytz
import yfinance as yf
import pandas as pd
import numpy as np
import feedparser
import requests
from config import *

def is_market_open() -> bool:
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:
        return False
    return dtime(4, 0) <= now.time() <= dtime(16, 0)

def session_label() -> str:
    et = pytz.timezone("America/New_York")
    now = datetime.now(et).time()
    if now < dtime(9, 30):
        return "Pre-Market"
    return "Regular"

def calculate_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    high = df["High"].squeeze()
    low = df["Low"].squeeze()
    close = df["Close"].squeeze()
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if pd.notna(atr) else float((high - low).iloc[-5:].mean())

def daytrade_plan(price: float, prev_high: float, prev_low: float, prev_close: float, atr: float) -> dict:
    pp = (prev_high + prev_low + prev_close) / 3
    r1 = 2 * pp - prev_low
    s1 = 2 * pp - prev_high
    r2 = pp + (prev_high - prev_low)
    s2 = pp - (prev_high - prev_low)

    buf = max(atr * 0.15, price * 0.002)

    if price <= s1:
        bias = "near support"
        entry = f"{s2:.2f}-{s1:.2f}"
        targets = f"{pp:.2f} then {r1:.2f}"
        invalid = f"below {s2:.2f}"
    elif price >= r1:
        bias = "near resistance"
        entry = f"{r1:.2f}-{r2:.2f}"
        targets = f"{pp:.2f} then {s1:.2f}"
        invalid = f"above {r2:.2f}"
    elif abs(price - pp) <= buf:
        bias = "around pivot"
        entry = f"{(pp - buf):.2f}-{(pp + buf):.2f}"
        targets = f"up {r1:.2f} / down {s1:.2f}"
        invalid = f"outside {s1:.2f}-{r1:.2f}"
    elif price > pp:
        bias = "above pivot"
        entry = f"{pp:.2f}-{(pp + buf):.2f}"
        targets = f"{r1:.2f} then {r2:.2f}"
        invalid = f"below {pp:.2f}"
    else:
        bias = "below pivot"
        entry = f"{(pp - buf):.2f}-{pp:.2f}"
        targets = f"{s1:.2f} then {s2:.2f}"
        invalid = f"above {pp:.2f}"

    return {
        "pp": pp, "s1": s1, "s2": s2, "r1": r1, "r2": r2,
        "atr": atr, "bias": bias,
        "entry": entry, "targets": targets, "invalid": invalid,
    }

def get_stock_signals(ticker: str) -> dict | None:
    try:
        data = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True)
        if data.empty or len(data) < 50:
            return None

        close = data["Close"].squeeze()
        high = data["High"].squeeze()
        low = data["Low"].squeeze()
        volume = data["Volume"].squeeze()

        current_price = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])
        prev_high = float(high.iloc[-2])
        prev_low = float(low.iloc[-2])

        try:
            live = yf.download(
                ticker, period="1d", interval="1m",
                progress=False, prepost=True, auto_adjust=True,
            )
            if live is not None and not live.empty:
                live_close = live["Close"].squeeze()
                if hasattr(live_close, "iloc") and len(live_close) > 0:
                    current_price = float(live_close.iloc[-1])
        except Exception:
            pass

        pct_change = ((current_price - prev_close) / prev_close) * 100
        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1])
        rsi = calculate_rsi(close)
        atr = calculate_atr(data)

        avg_vol_20 = float(volume.rolling(20).mean().iloc[-1])
        current_vol = float(volume.iloc[-1])
        vol_ratio = current_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

        signals = []
        if current_price > sma20 > sma50:
            signals.append("Bullish trend (Price > SMA20 > SMA50)")
        elif current_price < sma20 < sma50:
            signals.append("Bearish trend (Price < SMA20 < SMA50)")
        if rsi > RSI_OVERBOUGHT:
            signals.append(f"Overbought RSI {rsi:.1f}")
        elif rsi < RSI_OVERSOLD:
            signals.append(f"Oversold RSI {rsi:.1f}")
        if vol_ratio >= VOLUME_SPIKE_MULT:
            signals.append(f"Volume spike {vol_ratio:.1f}x avg")
        if abs(pct_change) >= PRICE_CHANGE_ALERT:
            direction = "up" if pct_change > 0 else "down"
            signals.append(f"Strong move {pct_change:+.1f}% {direction}")

        plan = daytrade_plan(current_price, prev_high, prev_low, prev_close, atr)

        return {
            "ticker": ticker,
            "price": current_price,
            "pct_change": pct_change,
            "rsi": rsi,
            "signals": signals,
            "plan": plan,
        }
    except Exception as e:
        print(f"Error {ticker}: {e}")
        return None

def get_news(ticker: str) -> list[dict]:
    news = []
    yahoo_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        feed = feedparser.parse(yahoo_url)
        for entry in feed.entries[:NEWS_LIMIT]:
            news.append({"title": entry.get("title", "")})
    except Exception:
        pass
    return news[:NEWS_LIMIT]

def score_news(title: str) -> str:
    title_lower = title.lower()
    pos = any(k in title_lower for k in POSITIVE_KEYWORDS)
    neg = any(k in title_lower for k in NEGATIVE_KEYWORDS)
    if pos and not neg:
        return "GREEN"
    if neg and not pos:
        return "RED"
    if pos and neg:
        return "MIXED"
    return ""

def send_telegram(message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Missing TELEGRAM secrets")
        print(message)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    try:
        r = requests.post(url, json=payload, timeout=10)
        print("Telegram sent" if r.ok else f"Telegram error: {r.text}")
    except Exception as e:
        print("Telegram send failed:", e)

def format_ticker(data: dict) -> str:
    p = data["plan"]
    lines = [
        f"{data['ticker']} ${data['price']:.2f} ({data['pct_change']:+.1f}%) RSI {data['rsi']:.0f}",
        f"ATR {p['atr']:.2f} | {p['bias']}",
        f"S2 {p['s2']:.2f} | S1 {p['s1']:.2f} | PP {p['pp']:.2f} | R1 {p['r1']:.2f} | R2 {p['r2']:.2f}",
        f"Entry {p['entry']}",
        f"Targets {p['targets']}",
        f"Invalid {p['invalid']}",
    ]
    if data["signals"]:
        lines.append("- " + " | ".join(data["signals"]))
    return "\n".join(lines)

def main():
    if not is_market_open():
        print("Market closed – skipping")
        return

    session = session_label()
    now_et = datetime.now(pytz.timezone("America/New_York"))
    print(f"Running at {now_et} ({session})")

    blocks = []
    for ticker in TICKERS:
        time.sleep(1.2)
        data = get_stock_signals(ticker)
        if not data:
            continue
        text = format_ticker(data)

        interesting_news = []
        for item in get_news(ticker):
            score = score_news(item["title"])
            if score:
                clean = item["title"].replace("<", "").replace(">", "")[:110]
                interesting_news.append(f"{score}: {clean}")
        if interesting_news:
            text += "\nNEWS: " + " | ".join(interesting_news[:2])
        blocks.append(text)

    if not blocks:
        print("No data")
        return

    header = (
        f"Stock Monitor - {session}\n"
        f"{now_et.strftime('%H:%M ET')}\n"
        "Levels only, not advice\n\n"
    )
    full_msg = header + "\n\n".join(blocks)
    if len(full_msg) > 4000:
        chunks = []
        current = header
        for block in blocks:
            if len(current) + len(block) + 2 > 3900:
                chunks.append(current)
                current = block + "\n\n"
            else:
                current += block + "\n\n"
        chunks.append(current)
        for chunk in chunks:
            send_telegram(chunk.strip())
            time.sleep(1)
    else:
        send_telegram(full_msg)

if __name__ == "__main__":
    main()

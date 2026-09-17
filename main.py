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
    """Check if US regular market hours (Mon-Fri 9:30-16:00 ET)"""
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:  # Sat/Sun
        return False
    market_open = dtime(9, 30)
    market_close = dtime(16, 0)
    return market_open <= now.time() <= market_close

def calculate_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0

def get_stock_signals(ticker: str) -> dict | None:
    try:
        # Batch-friendly + rate-limit friendly
        data = yf.download(ticker, period="3mo", interval="1d", progress=False, auto_adjust=True)
        if data.empty or len(data) < 50:
            return None

        close = data["Close"].squeeze()
        volume = data["Volume"].squeeze()

        current_price = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])
        pct_change = ((current_price - prev_close) / prev_close) * 100

        sma20 = float(close.rolling(20).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1])
        rsi = calculate_rsi(close)

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

        return {
            "ticker": ticker,
            "price": current_price,
            "pct_change": pct_change,
            "rsi": rsi,
            "sma20": sma20,
            "sma50": sma50,
            "vol_ratio": vol_ratio,
            "signals": signals
        }
    except Exception as e:
        print(f"Error {ticker}: {e}")
        return None

def get_news(ticker: str) -> list[dict]:
    news = []
    # Yahoo Finance RSS (very reliable for stocks)
    yahoo_url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    try:
        feed = feedparser.parse(yahoo_url)
        for entry in feed.entries[:NEWS_LIMIT]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            published = entry.get("published", "")
            news.append({"title": title, "link": link, "source": "Yahoo", "published": published})
    except Exception:
        pass

    # Google News as backup / extra coverage
    google_url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
    try:
        feed = feedparser.parse(google_url)
        for entry in feed.entries[:3]:
            title = entry.get("title", "")
            link = entry.get("link", "")
            if not any(n["title"] == title for n in news):
                news.append({"title": title, "link": link, "source": "Google", "published": entry.get("published", "")})
    except Exception:
        pass

    return news[:NEWS_LIMIT]

def score_news(title: str) -> str:
    title_lower = title.lower()
    pos = any(k in title_lower for k in POSITIVE_KEYWORDS)
    neg = any(k in title_lower for k in NEGATIVE_KEYWORDS)
    if pos and not neg:
        return "🟢 Potential positive"
    if neg and not pos:
        return "🔴 Potential negative"
    if pos and neg:
        return "🟡 Mixed"
    return ""

def send_telegram(message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        print(message)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print("Telegram error:", r.text)
    except Exception as e:
        print("Telegram send failed:", e)

def main():
    if not is_market_open():
        print("Market closed – skipping")
        return

    print(f"Running at {datetime.now(pytz.timezone('America/New_York'))}")

    alerts = []
    summary_lines = []

    for i, ticker in enumerate(TICKERS):
        time.sleep(1.2)  # polite delay to avoid Yahoo rate limits
        data = get_stock_signals(ticker)
        if not data:
            continue

        line = f"<b>{ticker}</b> ${data['price']:.2f} ({data['pct_change']:+.1f}%) | RSI {data['rsi']:.0f}"
        if data["signals"]:
            line += "\n• " + "\n• ".join(data["signals"])
            alerts.append(line)

        # News check
        news_items = get_news(ticker)
        interesting_news = []
        for item in news_items:
            score = score_news(item["title"])
            if score:
                interesting_news.append(f"{score}: {item['title'][:120]}")

        if interesting_news:
            news_text = f"\n📰 <b>{ticker} News</b>\n" + "\n".join(interesting_news[:3])
            alerts.append(news_text)

        summary_lines.append(f"{ticker}: {data['pct_change']:+.1f}% RSI{data['rsi']:.0f}")

    if alerts:
        header = f"🔔 <b>Stock Monitor – {datetime.now(pytz.timezone('America/New_York')).strftime('%H:%M ET')}</b>\n\n"
        full_msg = header + "\n\n".join(alerts)
        # Telegram has ~4096 char limit
        if len(full_msg) > 4000:
            full_msg = full_msg[:3900] + "\n\n... (truncated)"
        send_telegram(full_msg)
    else:
        # Optional quiet status (comment out if you only want alerts)
        quiet = f"✅ No strong signals\n" + " | ".join(summary_lines[:8])
        # send_telegram(quiet)   # uncomment if you want heartbeat messages
        print("No strong signals")

if __name__ == "__main__":
    main()

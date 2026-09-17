TICKERS = [
    "CRDO", "IREN", "PANW", "NBIS", "BMNR", "MSTR",
    "QBTS", "OKLO", "PLTR", "HUT", "INTC", "NNOX", "NVDA", "ALAR"
]

# Thresholds – tweak later
VOLUME_SPIKE_MULT = 2.0          # volume > 2x 20-day average
PRICE_CHANGE_ALERT = 3.0         # % change today
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# News keywords that often move stocks (my preferred starter list)
POSITIVE_KEYWORDS = [
    "beats", "beat estimates", "raises guidance", "raised guidance",
    "fda approval", "fda clears", "approval", "partnership", "collaboration",
    "acquisition", "acquires", "buyout", "upgrade", "upgraded",
    "record", "surge", "soars", "jumps", "wins contract", "new contract",
    "positive results", "phase 3", "breakthrough"
]

NEGATIVE_KEYWORDS = [
    "misses", "missed estimates", "cuts guidance", "lowered guidance",
    "lawsuit", "sued", "investigation", "probe", "downgrade", "downgraded",
    "sec", "fraud", "delay", "delayed", "halts", "halted", "warning",
    "weak", "disappointing", "below expectations"
]

# How many recent news items to check per ticker
NEWS_LIMIT = 5

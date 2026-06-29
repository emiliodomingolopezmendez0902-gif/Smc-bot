import os, time, schedule, requests, pandas as pd, numpy as np
from datetime import datetime, timezone
import yfinance as yf

TELEGRAM_TOKEN   = "8992966156:AAFEtAQNHcT0beACK1UWSSG3ytmyxTw-BG4"
TELEGRAM_CHAT_ID = "1977877526"

SYMBOL        = "GC=F"
TIMEFRAME     = "5m"
RISK_REWARD   = 2.5
OB_MIN_PIPS   = 3.0
FVG_MIN_PIPS  = 2.0
SL_BUFFER     = 1.5
LONDON_OPEN_UTC  = 8
LONDON_CLOSE_UTC = 12
NY_OPEN_UTC      = 13
NY_CLOSE_UTC     = 20
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        print(f"Mensaje enviado: {r.status_code}")
    except Exception as e:
        print(f"Error: {e}")

def get_ohlcv():
    try:
        ticker = yf.Ticker(SYMBOL)
        df = ticker.history(period="2d", interval=TIMEFRAME)
        if df.empty:
            return None
        df = df[["Open","High","Low","Close","Volume"]].copy()
        df.columns = ["open","high","low","close","volume"]
        df.dropna(inplace=True)
        return df
    except Exception as e:
        print(f"Error datos: {e}")
        return None

def detect_bias(df):
    ema8  = df["close"].ewm(span=8,  adjust=False).mean()
    ema21 = df["close"].ewm(span=21, adjust=False).mean()
    if ema8.iloc[-2] < ema21.iloc[-2]:
        return -1
    elif ema8.iloc[-2] > ema21.iloc[-2]:
        return 1
    return 0
def detect_bos(df, bias):
    lookback = min(30, len(df) - 2)
    recent = df.iloc[-lookback-1:-1]
    last_close = df["close"].iloc[-2]
    if bias == -1:
        return last_close < recent["low"].min()
    elif bias == 1:
        return last_close > recent["high"].max()
    return False

def detect_ob(df, bias):
    lookback = min(20, len(df) - 3)
    for i in range(2, lookback):
        idx = -(i + 1)
        o = df["open"].iloc[idx]
        h = df["high"].iloc[idx]
        l = df["low"].iloc[idx]
        c = df["close"].iloc[idx]
        ob_size = h - l
        if bias == -1 and c > o and ob_size >= OB_MIN_PIPS:
            future_low = df["low"].iloc[idx+1:idx+6].min()
            if (h - future_low) >= OB_MIN_PIPS * 2:
                return {"high": h, "low": l, "type": "bear"}
        elif bias == 1 and c < o and ob_size >= OB_MIN_PIPS:
            future_high = df["high"].iloc[idx+1:idx+6].max()
            if (future_high - l) >= OB_MIN_PIPS * 2:
                return {"high": h, "low": l, "type": "bull"}
    return None

def detect_fvg(df, bias):
    lookback = min(10, len(df) - 3)
    for i in range(1, lookback):
        h_prev = df["high"].iloc[-(i+2)]
        l_prev = df["low"].iloc[-(i+2)]
        h_next = df["high"].iloc[-i]
        l_next = df["low"].iloc[-i]
        if bias == -1 and h_next < l_prev and (l_prev - h_next) >= FVG_MIN_PIPS:
            return {"high": l_prev, "low": h_next}
        elif bias == 1 and l_next > h_prev and (l_next - h_prev) >= FVG_MIN_PIPS:
            return {"high": l_next, "low": h_prev}
    return None

def calc_rsi(df, period=14):
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss
    return round((100 - (100 / (1 + rs))).iloc[-2], 1)

def is_valid_session():
    h = datetime.now(timezone.utc).hour
    if LONDON_OPEN_UTC <= h < LONDON_CLOSE_UTC:
        return True, "🟡 LONDRES"
    if NY_OPEN_UTC <= h < NY_CLOSE_UTC:
        return True, "🟢 NEW YORK"
    return False, "🔴 Fuera de sesión"
last_signal_time = None

def check_signal():
    global last_signal_time
    valid_session, session_name = is_valid_session()
    if not valid_session:
        print("Fuera de sesión...")
        return
    df = get_ohlcv()
    if df is None or len(df) < 40:
        return
    bias = detect_bias(df)
    bos  = detect_bos(df, bias)
    ob   = detect_ob(df, bias)
    fvg  = detect_fvg(df, bias)
    rsi  = calc_rsi(df)
    price = df["close"].iloc[-1]
    if not bos or ob is None:
        return
    current_bar = df.index[-1]
    if last_signal_time == current_bar:
        return
    if bias == -1 and rsi < 70 and ob["low"] <= price <= ob["high"]:
        last_signal_time = current_bar
        entry = price
        sl    = ob["high"] + SL_BUFFER
        tp    = entry - (sl - entry) * RISK_REWARD
        msg = (
            f"⚡ <b>SEÑAL SMC — SELL</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Par: XAUUSD\n"
            f"🕐 Sesión: {session_name}\n"
            f"🔴 DIRECCIÓN: VENDER\n"
            f"🎯 Entrada: <code>{entry:.2f}</code>\n"
            f"🛑 Stop Loss: <code>{sl:.2f}</code>\n"
            f"💰 Take Profit: <code>{tp:.2f}</code>\n"
            f"📐 RR: 1:{RISK_REWARD}\n"
            f"📈 RSI: {rsi}\n"
            f"{'✅ FVG detectado' if fvg else ''}\n"
            f"⚠️ <i>Solo cuenta DEMO</i>"
        )
        send_telegram(msg)
    elif bias == 1 and rsi > 30 and ob["low"] <= price <= ob["high"]:
        last_signal_time = current_bar
        entry = price
        sl    = ob["low"] - SL_BUFFER
        tp    = entry + (entry - sl) * RISK_REWARD
        msg = (
            f"⚡ <b>SEÑAL SMC — BUY</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Par: XAUUSD\n"
            f"🕐 Sesión: {session_name}\n"
            f"🟢 DIRECCIÓN: COMPRAR\n"
            f"🎯 Entrada: <code>{entry:.2f}</code>\n"
            f"🛑 Stop Loss: <code>{sl:.2f}</code>\n"
            f"💰 Take Profit: <code>{tp:.2f}</code>\n"
            f"📐 RR: 1:{RISK_REWARD}\n"
            f"📈 RSI: {rsi}\n"
            f"{'✅ FVG detectado' if fvg else ''}\n"
            f"⚠️ <i>Solo cuenta DEMO</i>"
        )
        send_telegram(msg)

send_telegram("🤖 <b>SMC Scalper Bot ACTIVO ✅</b>\nEsperando señales en Londres y NY...")
schedule.every(5).minutes.do(check_signal)
check_signal()
while True:
    schedule.run_pending()
    time.sleep(30)

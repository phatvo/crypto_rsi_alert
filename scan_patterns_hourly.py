import os
import time
import requests
import pandas as pd
from datetime import datetime

GOOGLE_SHEET_WEBHOOK_URL = os.getenv("GOOGLE_SHEET_WEBHOOK_URL")
TIMEFRAME = "4h"
CANDLE_LIMIT = 80  # Chỉ cần lấy 80 nến gần nhất để tính chỉ báo và nhận diện đỉnh/đáy gần nhất

def append_to_sheet(payload: dict):
    if not GOOGLE_SHEET_WEBHOOK_URL:
        return
    try:
        resp = requests.post(GOOGLE_SHEET_WEBHOOK_URL, json=payload, timeout=10)
        print(f"-> [{payload['symbol']}] Sheet phản hồi: {resp.text.strip()}")
    except Exception as e:
        print(f"-> Lỗi gửi Sheet {payload['symbol']}: {e}")

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close, high, low, volume = df['close'], df['high'], df['low'], df['volume']
    
    # 1. RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    df['RSI'] = round(100 - (100 / (1 + (avg_gain / avg_loss))), 2)

    # 2. Bollinger Bands & Keltner Channels (KC 20 1)
    df['BB_Mid'] = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df['BB_Upper'] = df['BB_Mid'] + (bb_std * 2.0)
    df['BB_Lower'] = df['BB_Mid'] - (bb_std * 2.0)

    df['KC_Mid'] = close.ewm(span=20, adjust=False).mean()
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(10).mean()
    df['KC_Upper'] = df['KC_Mid'] + atr
    df['KC_Lower'] = df['KC_Mid'] - atr

    df['Is_Squeeze'] = (df['BB_Lower'] > df['KC_Lower']) & (df['BB_Upper'] < df['KC_Upper'])
    df['Squeeze_Fired'] = (~df['Is_Squeeze']) & (df['Is_Squeeze'].shift(1) == True)

    # 3. MACD & Volume MA20
    df['MACD_Hist'] = (close.ewm(span=12).mean() - close.ewm(span=26).mean()) - (close.ewm(span=12).mean() - close.ewm(span=26).mean()).ewm(span=9).mean()
    df['Vol_MA20'] = volume.rolling(20).mean()
    df['Vol_Ratio'] = round(volume / df['Vol_MA20'], 2)
    df['Vol_Breakout'] = volume > (df['Vol_MA20'] * 1.5)
    return df

def scan_latest_candle(symbol: str):
    url = "https://data-api.binance.vision/api/v3/klines"
    try:
        resp = requests.get(url, params={"symbol": symbol, "interval": TIMEFRAME, "limit": CANDLE_LIMIT}, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 50:
            return

        df = pd.DataFrame(data, columns=["open_time","open","high","low","close","volume","close_time","q_vol","trades","tb_base","tb_quote","ignore"])
        df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        df = calculate_indicators(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        time_str = str(curr['datetime'])

        # Kiểm tra Bung Nén TTM Squeeze tại nến hiện tại
        if curr['Squeeze_Fired'] and curr['Vol_Breakout']:
            direction = "TĂNG" if curr['MACD_Hist'] > 0 else "GIẢM"
            append_to_sheet({
                "symbol": symbol,
                "time": time_str,
                "signal_type": f"SQUEEZE_FIRED_{direction}",
                "trigger_price": curr['close'],
                "neckline_price": round(curr['BB_Mid'], 4),
                "rsi_weekly": 0.0,
                "rsi_current": curr['RSI'],
                "macd_hist": round(curr['MACD_Hist'], 4),
                "is_squeeze": False,
                "vol_ratio": f"{curr['Vol_Ratio']}x",
                "notes": f"Bung nén Bollinger trong Keltner (KC 20 1) hướng {direction}. Vol: {curr['Vol_Ratio']}x"
            })
    except Exception as e:
        print(f"Lỗi {symbol}: {e}")

def main():
    try:
        tickers = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=15).json()
        symbols = [t['symbol'] for t in tickers if isinstance(t, dict) and t.get('symbol', '').endswith('USDT')]
    except Exception as e:
        print(f"Lỗi lấy danh sách coin: {e}")
        return

    print(f"Bắt đầu quét {len(symbols)} coin...")
    for sym in symbols:
        scan_latest_candle(sym)
        time.sleep(0.05)
    print("Hoàn tất quét.")

if __name__ == "__main__":
    main()

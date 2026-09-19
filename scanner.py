import os
import time
import requests
import pandas as pd

# ================= CẤU HÌNH NGƯỠNG LỌC =================
# Ngưỡng quét RSI & 24h (Gửi về TELEGRAM_CHAT_ID)
PRICE_CHANGE_THRESHOLD = 65.0      # Tăng trưởng 24h >= 65%
RSI_4H_THRESHOLD = 80.0            # RSI 4h > 80
RSI_12H_THRESHOLD = 85.0           # RSI 12h > 85
RSI_24H_THRESHOLD = 85.0           # RSI 24h > 85

# Ngưỡng quét 2 nến 15m (Gửi về TELEGRAM_CHAT_ID_LONG)
PRICE_CHANGE_24H_THRESHOLD = 5.5   # Lọc các coin 24h > 5.5% để quét 15m
THRESHOLD_15M_PERCENT = 3.0        # Cả 2 nến 15m đều tăng > 3%

# ================= LẤY THÔNG TIN TỪ SECRETS =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_CHAT_ID_LONG = os.getenv("TELEGRAM_CHAT_ID_LONG")

def send_telegram_alert(message: str):
    """Gửi cảnh báo RSI & 24h qua Telegram Bot"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Lỗi]: Thiếu cấu hình Token hoặc Chat ID trong Secrets")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        res = resp.json()
        if res.get("ok"):
            print("-> [Thành công] Đã gửi cảnh báo RSI đến Telegram!")
        else:
            print(f"-> [Lỗi Telegram]: {res.get('description')}")
    except Exception as e:
        print(f"-> [Lỗi kết nối Telegram]: {e}")

def send_telegram_alert_long(message: str):
    """Gửi cảnh báo nến 15m qua Telegram Bot"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID_LONG:
        print("[Lỗi]: Thiếu cấu hình Token hoặc Chat ID LONG trong Secrets")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID_LONG, 
        "text": message, 
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        res = resp.json()
        if res.get("ok"):
            print("-> [Thành công] Đã gửi cảnh báo 15m đến Telegram LONG!")
        else:
            print(f"-> [Lỗi Telegram]: {res.get('description')}")
    except Exception as e:
        print(f"-> [Lỗi kết nối Telegram]: {e}")

def calculate_rsi(prices, period: int = 14) -> float:
    """Tính chỉ số RSI theo phương pháp Wilder's Smoothing"""
    if len(prices) < period + 1:
        return 0.0
    series = pd.Series(prices)
    delta = series.diff()

    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)

def get_binance_rsi(symbol: str, interval: str, limit: int = 100) -> float:
    """Lấy dữ liệu nến từ cổng data-api của Binance (Không bị chặn IP)"""
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        closes = [float(kline[4]) for kline in data]
        return calculate_rsi(closes)
    except Exception as e:
        print(f"Lỗi lấy nến {symbol} ({interval}): {e}")
        return 0.0

def check_15m_candles(symbol: str):
    """Lấy dữ liệu nến 15m và tính biến động nến hiện tại (n) và nến trước (n-1)"""
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": "15m", "limit": 5}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return None

        # Nến hiện tại (n) - index -1
        open_n = float(data[-1])   # Vị trí: Giá mở cửa
        close_n = float(data[-1])  # Vị trí: Giá đóng cửa / hiện tại
        change_n = ((close_n - open_n) / open_n) * 100

        # Nến liền trước (n-1) - index -2
        open_prev = float(data[-2])   # Vị trí: Giá mở cửa
        close_prev = float(data[-2])  # Vị trí: Giá đóng cửa
        change_prev = ((close_prev - open_prev) / open_prev) * 100

        return {
            "current_price": close_n,
            "change_n": round(change_n, 2),
            "change_prev": round(change_prev, 2)
        }
    except Exception as e:
        print(f"Lỗi lấy nến 15m của {symbol}: {e}")
        return None

def scan_market():
    """Quét thị trường 1 lần xử lý cả 2 điều kiện"""
    print("Bắt đầu quét biến động giá 24h...")
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    try:
        resp = requests.get(url, timeout=15)
        tickers = resp.json()
    except Exception as e:
        print(f"Lỗi kết nối API: {e}")
        return

    if not isinstance(tickers, list):
        print(f"[Cảnh báo API]: Binance phản hồi: {tickers}")
        return

    # -------------------------------------------------------------
    # NHIỆM VỤ 1: Quét RSI & Biến động 24h >= 65% (Gửi vào TELEGRAM_CHAT_ID)
    # -------------------------------------------------------------
    matched_candidates = [
        t for t in tickers
        if isinstance(t, dict) and t.get("symbol", "").endswith("USDT") and float(t.get("priceChangePercent", 0)) >= PRICE_CHANGE_THRESHOLD
    ]
    print(f"\n--- [Nhiệm vụ 1] Tìm thấy {len(matched_candidates)} coin có biến động >= {PRICE_CHANGE_THRESHOLD}% ---")
    
    for coin in matched_candidates:
        symbol = coin["symbol"]
        price = float(coin["lastPrice"])
        price_change = float(coin["priceChangePercent"])

        rsi_4h = get_binance_rsi(symbol, "4h")
        rsi_12h = get_binance_rsi(symbol, "12h")
        rsi_24h = get_binance_rsi(symbol, "1d")

        print(f"-> {symbol}: 24h = +{price_change:.2f}%, RSI 4h = {rsi_4h}, 12h = {rsi_12h}, 24h = {rsi_24h}")

        if rsi_4h > RSI_4H_THRESHOLD and rsi_12h > RSI_12H_THRESHOLD and rsi_24h > RSI_24H_THRESHOLD:
            msg = (
                f"🚨 *COIN ALERT THỎA ĐIỀU KIỆN!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{price}`\n"
                f"• *Price Change (24h)*: `+{price_change:.2f}%` (>= {PRICE_CHANGE_THRESHOLD}%)\n"
                f"• *RSI (4h)*: `{rsi_4h}` (> {RSI_4H_THRESHOLD})\n"
                f"• *RSI (12h)*: `{rsi_12h}` (> {RSI_12H_THRESHOLD})\n"
                f"• *RSI (24h)*: `{rsi_24h}` (> {RSI_24H_THRESHOLD})\n"
            )
            send_telegram_alert(msg)
        time.sleep(0.3)

    # -------------------------------------------------------------
    # NHIỆM VỤ 2: Quét 2 nến 15m liên tiếp > 3% cho coin 24h > 5.5% (Gửi vào TELEGRAM_CHAT_ID_LONG)
    # -------------------------------------------------------------
    candidates_15m = [
        t for t in tickers
        if isinstance(t, dict) and t.get("symbol", "").endswith("USDT") and float(t.get("priceChangePercent", 0)) > PRICE_CHANGE_24H_THRESHOLD
    ]
    print(f"\n--- [Nhiệm vụ 2] Tìm thấy {len(candidates_15m)} coin có biến động 24h > {PRICE_CHANGE_24H_THRESHOLD}% ---")

    for coin in candidates_15m:
        symbol = coin["symbol"]
        price_change_24h = float(coin["priceChangePercent"])
        
        candle_info = check_15m_candles(symbol)
        if not candle_info:
            continue

        change_n = candle_info["change_n"]
        change_prev = candle_info["change_prev"]
        current_price = candle_info["current_price"]

        print(f"-> {symbol} (24h: +{price_change_24h:.2f}%): Nến n = {change_n:+.2f}%, Nến n-1 = {change_prev:+.2f}%")

        if change_n > THRESHOLD_15M_PERCENT and change_prev > THRESHOLD_15M_PERCENT:
            total_15m = round(change_n + change_prev, 2)
            msg = (
                f"⚡ *CẢNH BÁO PUMP 2 NẾN 15M LIÊN TIẾP!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{current_price}`\n"
                f"• *Tăng 24h*: `+{price_change_24h:.2f}%` (> {PRICE_CHANGE_24H_THRESHOLD}%)\n"
                f"• *Nến 15m hiện tại (n)*: `+{change_n:.2f}%` (> {THRESHOLD_15M_PERCENT}%)\n"
                f"• *Nến 15m trước đó (n-1)*: `+{change_prev:.2f}%` (> {THRESHOLD_15M_PERCENT}%)\n"
                f"• *Tổng tăng 2 nến 15m*: `+{total_15m:.2f}%`\n"
            )
            send_telegram_alert_long(msg)
            
        time.sleep(0.3)

if __name__ == "__main__":
    scan_market()
    print("\nQuét hoàn tất.")

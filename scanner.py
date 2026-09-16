import os
import time
import requests
import pandas as pd

# Cấu hình ngưỡng lọc
PRICE_CHANGE_THRESHOLD = 65.0  # Tăng trưởng 24h > 60%
RSI_4H_THRESHOLD = 80.0          # RSI 4h > 80
PRICE_CHANGE_THRESHOLD_LONG = 33.0  # Tăng trưởng 24h > 33%
RSI_4H_THRESHOLD_LONG = 50.0          # RSI 4h > 50
RSI_12H_THRESHOLD = 85.0          # RSI 12h > 85
RSI_24H_THRESHOLD = 85.0          # RSI 24h > 85
CHECK_INTERVAL_SECONDS = 300  # Quét lại sau mỗi 5 phút (300 giây)

# Lấy thông tin từ GitHub Secrets
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_CHAT_ID_LONG = os.getenv("TELEGRAM_CHAT_ID_LONG")

def send_telegram_alert_long(message: str):
    """Gửi cảnh báo qua Telegram Bot"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID_LONG:
        print("[Lỗi]: Thiếu cấu hình Token hoặc Chat ID trong Secrets")
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
            print("-> [Thành công] Đã gửi tin nhắn đến Telegram!")
        else:
            print(f"-> [Lỗi Telegram]: {res.get('description')}")
    except Exception as e:
        print(f"-> [Lỗi kết nối Telegram]: {e}")
        
def send_telegram_alert(message: str):
    """Gửi cảnh báo qua Telegram Bot"""
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
            print("-> [Thành công] Đã gửi tin nhắn đến Telegram!")
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
    # Đổi từ:
    url = "https://data-api.binance.vision/api/v3/klines"
    # Thành:
    # url = "https://fapi.binance.com/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        closes = [float(kline[4]) for kline in data]
        return calculate_rsi(closes)
    except Exception as e:
        print(f"Lỗi lấy nến {symbol} ({interval}): {e}")
        return 0.0

def scan_market():
    """Quét thị trường 1 lần"""
    print("Bắt đầu quét biến động giá 24h...")
    # Sử dụng endpoint data-api.binance.vision không giới hạn vị trí địa lý
    # Đổi từ:
    url = "https://data-api.binance.vision/api/v3/ticker/24hr"
    # Thành:
    # url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        resp = requests.get(url, timeout=15)
        tickers = resp.json()
    except Exception as e:
        print(f"Lỗi kết nối API: {e}")
        return

    # Kiểm tra tính hợp lệ của dữ liệu trả về
    if not isinstance(tickers, list):
        print(f"[Cảnh báo API]: Binance phản hồi: {tickers}")
        return

    matched_candidates = [
        t for t in tickers
        if isinstance(t, dict) and t.get("symbol", "").endswith("USDT") and float(t.get("priceChangePercent", 0)) >= PRICE_CHANGE_THRESHOLD
    ]
    print(f"Tìm thấy {len(matched_candidates)} coin có biến động >= {PRICE_CHANGE_THRESHOLD}%")
    
    
    for coin in matched_candidates:
        symbol = coin["symbol"]
        price = float(coin["lastPrice"])
        price_change = float(coin["priceChangePercent"])

        rsi_4h = get_binance_rsi(symbol, "4h")
        rsi_12h = get_binance_rsi(symbol, "12h")
        rsi_24h = get_binance_rsi(symbol, "1d")

        print(f"-> {symbol}: Price Change = +{price_change:.2f}%, RSI 4h = {rsi_4h}, 12h = {rsi_12h}, 24h = {rsi_24h}")

        if rsi_4h > RSI_4H_THRESHOLD and rsi_12h > RSI_12H_THRESHOLD and rsi_24h > RSI_24H_THRESHOLD:
            msg = (
                f"🚨 *COIN ALERT THỎA ĐIỀU KIỆN!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{price}`\n"
                f"• *Price Change (24h) >* `{PRICE_CHANGE_THRESHOLD:.2f}%` : `+{price_change:.2f}%`\n"
                f"• *RSI (4h) >* `{RSI_4H_THRESHOLD}`: `{rsi_4h}`\n"
                f"• *RSI (12h) >* `{RSI_12H_THRESHOLD}`: `{rsi_12h}`\n"
                f"• *RSI (24h) >* `{RSI_24H_THRESHOLD}`: `{rsi_24h}`\n"
            )
            send_telegram_alert(msg)
        time.sleep(0.5)

    matched_candidates_long = [
        t for t in tickers
        if isinstance(t, dict) and t.get("symbol", "").endswith("USDT") and float(t.get("priceChangePercent", 0)) >= PRICE_CHANGE_THRESHOLD_LONG
    ]

    print(f"Tìm thấy {len(matched_candidates_long)} coin có biến động >= {PRICE_CHANGE_THRESHOLD_LONG}%")
    
    for coin in matched_candidates_long:
        symbol = coin["symbol"]
        price = float(coin["lastPrice"])
        price_change = float(coin["priceChangePercent"])

        rsi_4h = get_binance_rsi(symbol, "4h")
        rsi_12h = get_binance_rsi(symbol, "12h")
        rsi_24h = get_binance_rsi(symbol, "1d")

        print(f"-> {symbol}: Price Change = +{price_change:.2f}%, RSI 4h = {rsi_4h}, 12h = {rsi_12h}, 24h = {rsi_24h}")

        if rsi_4h > 5:
            msg = (
                f"🚨 *COIN ALERT THỎA ĐIỀU KIỆN LONG!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{price}`\n"
                f"• *Price Change (24h) >* `{PRICE_CHANGE_THRESHOLD_LONG:.2f}%` : `+{price_change:.2f}%`\n"
                f"• *RSI (4h) >* `{RSI_4H_THRESHOLD_LONG}`: `{rsi_4h}`\n"
                f"• *RSI (12h) >* `{RSI_12H_THRESHOLD}`: `{rsi_12h}`\n"
                f"• *RSI (24h) >* `{RSI_24H_THRESHOLD}`: `{rsi_24h}`\n"
            )
            send_telegram_alert_long(msg)
        time.sleep(0.5)

if __name__ == "__main__":
    scan_market()
    print("Quét hoàn tất.")

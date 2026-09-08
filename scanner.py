import time
import requests
import pandas as pd

# Cấu hình ngưỡng lọc
PRICE_CHANGE_THRESHOLD = 75.0  # Tăng trưởng 24h > 60%
RSI_THRESHOLD = 85.0          # RSI 4h, 12h, 24h > 60
CHECK_INTERVAL_SECONDS = 300  # Quét lại sau mỗi 5 phút (300 giây)

# Lấy thông tin từ GitHub Secrets
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_alert(message: str):
    """Gửi cảnh báo qua Telegram Bot"""
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print(f"[Trigger]: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")

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
    """Lấy dữ liệu nến và tính RSI từ Binance API"""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        closes = [float(kline[4]) for kline in data]
        return calculate_rsi(closes)
    except Exception as e:
        print(f"Lỗi lấy dữ liệu nến {symbol} ({interval}): {e}")
        return 0.0

def scan_market():
    """Quét toàn bộ thị trường và kiểm tra điều kiện"""
    print("Đang quét biến động giá 24h...")
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        tickers = requests.get(url, timeout=15).json()
    except Exception as e:
        print(f"Lỗi lấy dữ liệu ticker 24h: {e}")
        return

    # Lọc các cặp giao dịch USDT có biến động giá 24h >= 60%
    matched_candidates = [
        t for t in tickers
        if t["symbol"].endswith("USDT") and float(t["priceChangePercent"]) >= PRICE_CHANGE_THRESHOLD
    ]

    print(f"Tìm thấy {len(matched_candidates)} coin có biến động 24h >= {PRICE_CHANGE_THRESHOLD}%")

    for coin in matched_candidates:
        symbol = coin["symbol"]
        price = float(coin["lastPrice"])
        price_change = float(coin["priceChangePercent"])

        # Kiểm tra RSI ở các khung 4h, 12h, 1d (24h)
        rsi_4h = get_binance_rsi(symbol, "4h")
        rsi_12h = get_binance_rsi(symbol, "12h")
        rsi_24h = get_binance_rsi(symbol, "1d")

        print(f"-> {symbol}: Price Change = +{price_change:.2f}%, RSI 4h = {rsi_4h}, 12h = {rsi_12h}, 24h = {rsi_24h}")

        # Điều kiện trigger: cả 3 khung RSI đều > 60
        if rsi_4h > RSI_THRESHOLD and rsi_12h > RSI_THRESHOLD and rsi_24h > RSI_THRESHOLD:
            msg = (
                f"🚨 *COIN ALERT THỎA ĐIỀU KIỆN!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{price}`\n"
                f"• *Price Change (24h)*: `+{price_change:.2f}%`\n"
                f"• *RSI (4h)*: `{rsi_4h}`\n"
                f"• *RSI (12h)*: `{rsi_12h}`\n"
                f"• *RSI (24h)*: `{rsi_24h}`\n"
            )
            send_telegram_alert(msg)
        
        # Nghỉ ngắn giữa các coin để tránh giới hạn request
        time.sleep(0.5)

if __name__ == "__main__":
    print("Khởi động hệ thống quét cảnh báo RSI & Price Change...")
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Lỗi trong vòng lặp quét: {e}")
        time.sleep(CHECK_INTERVAL_SECONDS)

import os
import time
import requests

# Cấu hình ngưỡng lọc
THRESHOLD_15M_PERCENT = 3.0  # Ngưỡng tăng nến 15m > 3%

# Lấy thông tin từ GitHub Secrets
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID_LONG = os.getenv("TELEGRAM_CHAT_ID_LONG")

def send_telegram_alert_long(message: str):
    """Gửi cảnh báo đến nhóm TELEGRAM_CHAT_ID_LONG"""
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
            print("-> [Thành công] Đã gửi cảnh báo 15m đến Telegram!")
        else:
            print(f"-> [Lỗi Telegram]: {res.get('description')}")
    except Exception as e:
        print(f"-> [Lỗi kết nối Telegram]: {e}")

def check_15m_candles(symbol: str):
    """Lấy dữ liệu nến 15m và tính biến động của nến hiện tại (n) và nến trước (n-1)"""
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": "15m", "limit": 5}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return None

        # Nến hiện tại (n) - index -1
        open_n = float(data[-1])
        close_n = float(data[-1])  # Giá hiện tại
        change_n = ((close_n - open_n) / open_n) * 100

        # Nến liền trước (n-1) - index -2
        open_prev = float(data[-2])
        close_prev = float(data[-2])
        change_prev = ((close_prev - open_prev) / open_prev) * 100

        return {
            "current_price": close_n,
            "change_n": round(change_n, 2),
            "change_prev": round(change_prev, 2)
        }
    except Exception as e:
        print(f"Lỗi lấy nến 15m của {symbol}: {e}")
        return None

def scan_market_15m():
    """Quét thị trường tìm coin có 2 nến 15m liên tiếp tăng > 3%"""
    print("Bắt đầu quét biến động nến 15m...")
    
    # Lọc nhanh các coin có biến động trong 15m qua >= 2.5% để tiết kiệm request
    url = "https://data-api.binance.vision/api/v3/ticker?windowSize=15m"
    try:
        resp = requests.get(url, timeout=15)
        tickers = resp.json()
    except Exception as e:
        print(f"Lỗi kết nối API ticker 15m: {e}")
        return

    if not isinstance(tickers, list):
        print(f"[Cảnh báo API]: Phản hồi không hợp lệ: {tickers}")
        return

    candidates = [
        t for t in tickers
        if isinstance(t, dict) and t.get("symbol", "").endswith("USDT") and float(t.get("priceChangePercent", 0)) >= 2.5
    ]

    print(f"Tìm thấy {len(candidates)} coin có biến động 15m gần nhất >= 2.5%")

    for coin in candidates:
        symbol = coin["symbol"]
        candle_info = check_15m_candles(symbol)
        
        if not candle_info:
            continue

        change_n = candle_info["change_n"]
        change_prev = candle_info["change_prev"]
        current_price = candle_info["current_price"]

        print(f"-> {symbol}: Nến (n) = {change_n:+.2f}%, Nến (n-1) = {change_prev:+.2f}%")

        # Điều kiện: Cả nến hiện tại (n) và nến trước (n-1) đều tăng > 3%
        if change_n > THRESHOLD_15M_PERCENT and change_prev > THRESHOLD_15M_PERCENT:
            total_change = round(change_n + change_prev, 2)
            msg = (
                f"⚡ *CẢNH BÁO PUMP 2 NẾN 15M LIÊN TIẾP!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{current_price}`\n"
                f"• *Nến 15m hiện tại (n)*: `+{change_n:.2f}%` (> 3%)\n"
                f"• *Nến 15m trước đó (n-1)*: `+{change_prev:.2f}%` (> 3%)\n"
                f"• *Tổng tăng 2 nến*: `+{total_change:.2f}%`\n"
            )
            send_telegram_alert_long(msg)
            
        time.sleep(0.3)

if __name__ == "__main__":
    scan_market_15m()
    print("Quét 15m hoàn tất.")

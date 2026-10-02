import os
import time
import requests
import pandas as pd
from datetime import datetime

# ================= CẤU HÌNH NGƯỠNG LỌC =================
# Ngưỡng quét RSI & 24h (Gửi về TELEGRAM_CHAT_ID)
PRICE_CHANGE_THRESHOLD = 65.0      # Tăng trưởng 24h >= 65%
RSI_4H_THRESHOLD = 80.0            # RSI 4h > 80
RSI_12H_THRESHOLD = 85.0           # RSI 12h > 85
RSI_24H_THRESHOLD = 85.0           # RSI 24h > 85

# Ngưỡng quét LONG (Gửi về TELEGRAM_CHAT_ID_LONG)
PRICE_CHANGE_THRESHOLD_LONG = 20.0  # Tăng trưởng 24h >= 20%
RSI_4H_THRESHOLD_LONG = 35.0        # RSI 4h > 35
RSI_12H_THRESHOLD_LONG = 60.0       # RSI 12h > 60
RSI_24H_THRESHOLD_LONG = 60.0       # RSI 24h > 60
RSI_12H_THRESHOLD_LONG_UP = 85.0    # RSI 12h < 85
RSI_24H_THRESHOLD_LONG_UP = 85.0    # RSI 24h < 85
THRESHOLD_4H_RATIO = 2.0

# Ngưỡng quét SHORT WEEK (Gửi về TELEGRAM_CHAT_ID_RSI_WEEK)
RSI_SHORT_WEEK_THRESHOLD_UP = 93.0  # RSI Tuần > 93
RSI_SHORT_24H_THRESHOLD_UP = 50.0   # RSI 24h < 50
PRICE_CHANGE_THRESHOLD_SHORT = -10.0 # Giảm giá 24h <= -10%

# Ngưỡng quét 2 nến 15m
PRICE_CHANGE_24H_THRESHOLD = 5.5   # Lọc các coin 24h > 5.5% để quét 15m
THRESHOLD_15M_PERCENT = 3.0        # Cả 2 nến 15m đều tăng > 3%

# ================= LẤY THÔNG TIN TỪ SECRETS =================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_CHAT_ID_LONG = os.getenv("TELEGRAM_CHAT_ID_LONG")
TELEGRAM_CHAT_ID_RSI_WEEK = os.getenv("TELEGRAM_CHAT_ID_RSI_WEEK")
TELEGRAM_CHAT_ID_RSI_BOT_STATUS = os.getenv("TELEGRAM_CHAT_ID_RSI_BOT_STATUS")

def send_telegram_rsi_status(message: str):
    """Gửi nhật ký trạng thái quét qua Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID_RSI_BOT_STATUS:
        return
    if not message.strip():
        message = "ℹ️ Quét hoàn tất: Không có coin nào đạt mức tăng >= 20%."
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID_RSI_BOT_STATUS, 
        "text": f"📊 *BÁO CÁO QUÉT THỊ TRƯỜNG:*\n```\n{message[:3900]}\n```", 
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Lỗi gửi status: {e}")

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

def send_telegram_alert_rsi_week(message: str):
    """Gửi cảnh báo RSI Week qua Telegram Bot"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID_RSI_WEEK:
        print("[Lỗi]: Thiếu cấu hình Token hoặc Chat ID RSI WEEK trong Secrets")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID_RSI_WEEK, 
        "text": message, 
        "parse_mode": "Markdown"
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        res = resp.json()
        if res.get("ok"):
            print("-> [Thành công] Đã gửi cảnh báo Telegram rsi week!")
        else:
            print(f"-> [Lỗi Telegram]: {res.get('description')}")
    except Exception as e:
        print(f"-> [Lỗi kết nối Telegram]: {e}")

def send_telegram_alert_long(message: str):
    """Gửi cảnh báo LONG qua Telegram Bot"""
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
            print("-> [Thành công] Đã gửi cảnh báo Telegram LONG!")
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

def get_binance_rsi_week_data(symbol: str, limit: int = 100):
    """Lấy RSI khung tuần của nến hiện tại (n) và nến trước đó (n-1)"""
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": "1w", "limit": limit}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 16:
            return 0.0, 0.0
        closes = [float(kline[4]) for kline in data]
        series = pd.Series(closes)
        delta = series.diff()

        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return round(float(rsi.iloc[-1]), 2), round(float(rsi.iloc[-2]), 2)
    except Exception as e:
        print(f"Lỗi lấy RSI tuần của {symbol}: {e}")
        return 0.0, 0.0

def check_15m_candles(symbol: str):
    """Lấy dữ liệu nến 15m và tính biến động nến hiện tại (n) và nến trước (n-1)"""
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": "15m", "limit": 5}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return None

        _, open_n_str, _, _, close_n_str, *_ = data[-1]
        open_n = float(open_n_str)
        close_n = float(close_n_str)
        change_n = ((close_n - open_n) / open_n) * 100

        _, open_prev_str, _, _, close_prev_str, *_ = data[-2]
        open_prev = float(open_prev_str)
        close_prev = float(close_prev_str)
        change_prev = ((close_prev - open_prev) / open_prev) * 100

        return {
            "current_price": close_n,
            "change_n": round(change_n, 2),
            "change_prev": round(change_prev, 2)
        }
    except Exception as e:
        print(f"Lỗi lấy nến 15m của {symbol}: {e}")
        return None

def check_4h_candles(symbol: str):
    """Lấy dữ liệu nến 4h và tính biến động cùng 4 mức giá OHLC của nến n và n-1"""
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": "4h", "limit": 5}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return None

        # 1. Trích xuất OHLC của nến hiện tại (n) - data[-1]
        _, open_n_str, high_n_str, low_n_str, close_n_str, *_ = data[-1]
        open_n = float(open_n_str)
        high_n = float(high_n_str)
        low_n = float(low_n_str)
        close_n = float(close_n_str)
        change_n = ((close_n - open_n) / open_n) * 100

        # 2. Trích xuất OHLC của nến trước đó (n-1) - data[-2]
        _, open_prev_str, high_prev_str, low_prev_str, close_prev_str, *_ = data[-2]
        open_prev = float(open_prev_str)
        high_prev = float(high_prev_str)
        low_prev = float(low_prev_str)
        close_prev = float(close_prev_str)
        change_prev = ((close_prev - open_prev) / open_prev) * 100

        return {
            "current_price": close_n,
            "change_n": round(change_n, 2),
            "change_prev": round(change_prev, 2),
            "open_4h_n": open_n,
            "high_4h_n": high_n,
            "low_4h_n": low_n,
            "close_4h_n": close_n,
            "open_4h_prev": open_prev,
            "high_4h_prev": high_prev,
            "low_4h_prev": low_prev,
            "close_4h_prev": close_prev
        }
    except Exception as e:
        print(f"Lỗi lấy nến 4h của {symbol}: {e}")
        return None

def check_1h_candles(symbol: str):
    """Lấy dữ liệu nến 1h và tính biến động nến hiện tại (n) và nến trước (n-1)"""
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": "1h", "limit": 5}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return None

        _, open_n_str, _, _, close_n_str, *_ = data[-1]
        open_n = float(open_n_str)
        close_n = float(close_n_str)
        change_n = ((close_n - open_n) / open_n) * 100

        _, open_prev_str, _, _, close_prev_str, *_ = data[-2]
        open_prev = float(open_prev_str)
        close_prev = float(close_prev_str)
        change_prev = ((close_prev - open_prev) / open_prev) * 100

        return {
            "current_price": close_n,
            "change_n": round(change_n, 2),
            "change_prev": round(change_prev, 2)
        }
    except Exception as e:
        print(f"Lỗi lấy nến 1h của {symbol}: {e}")
        return None

def fmt_price(p: float) -> str:
    """Định dạng mức giá hiển thị linh hoạt số chữ số thập phân"""
    if p < 0.001:
        return f"{p:.6f}"
    elif p < 1:
        return f"{p:.5f}"
    else:
        return f"{p:.2f}"

def scan_market():
    """Quét toàn bộ thị trường theo các tiêu chí đã định nghĩa"""
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

    # =============================================================
    # NHÓM 1: CÁC COIN TĂNG TRƯỞNG MẠNH 24H >= 20%
    # =============================================================
    matched_candidates = [
        t for t in tickers
        if isinstance(t, dict) and t.get("symbol", "").endswith("USDT") and float(t.get("priceChangePercent", 0)) >= PRICE_CHANGE_THRESHOLD_LONG
    ]

    rsi_bot_status_msg = ""
    step_msg = f"\n--- [Nhiệm vụ Tăng] Tìm thấy {len(matched_candidates)} coin có biến động >= {PRICE_CHANGE_THRESHOLD_LONG}% ---"
    print(step_msg)

    for coin in matched_candidates:
        symbol = coin["symbol"]
        price = float(coin["lastPrice"])
        price_change = float(coin["priceChangePercent"])

        rsi_4h = get_binance_rsi(symbol, "4h")
        rsi_12h = get_binance_rsi(symbol, "12h")
        rsi_24h = get_binance_rsi(symbol, "1d")
        rsi_week_n, rsi_week_prev = get_binance_rsi_week_data(symbol)

        step_msg = f"\n-> {symbol}: 24h = +{price_change:.2f}%, RSI 4h = {rsi_4h}, 12h = {rsi_12h}, 24h = {rsi_24h}, 1W = {rsi_week_n}"
        print(step_msg)
        rsi_bot_status_msg += step_msg

        # --- ĐIỀU KIỆN SHORT 1: Coin đang tăng mạnh nhưng RSI Tuần (n) đạt đỉnh quá mua > 93 ---
        if rsi_week_n > RSI_SHORT_WEEK_THRESHOLD_UP:
            msg_short_week = (
                f"🚨 *CẢNH BÁO SHORT (BẮT ĐỈNH TUẦN ĐANG TĂNG)!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{fmt_price(price)}`\n"
                f"• *Price Change (24h)*: `+{price_change:.2f}%`\n"
                f"• *RSI Tuần hiện tại (n)*: `{rsi_week_n}` (> {RSI_SHORT_WEEK_THRESHOLD_UP})\n"
                f"• *RSI (24h)*: `{rsi_24h}` | *12h*: `{rsi_12h}` | *4h*: `{rsi_4h}`\n"
            )
            send_telegram_alert_rsi_week(msg_short_week)

        # --- ĐIỀU KIỆN SHORT CŨ: 24h >= 65%, RSI 4h > 80, 12h > 85, 24h > 85 ---
        if (price_change >= PRICE_CHANGE_THRESHOLD and 
            rsi_4h > RSI_4H_THRESHOLD and 
            rsi_12h > RSI_12H_THRESHOLD and 
            rsi_24h > RSI_24H_THRESHOLD):
            msg_short = (
                f"🚨 *COIN ALERT THỎA ĐIỀU KIỆN SHORT!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{fmt_price(price)}`\n"
                f"• *Price Change (24h)*: `+{price_change:.2f}%` (>= {PRICE_CHANGE_THRESHOLD}%)\n"
                f"• *RSI (4h)*: `{rsi_4h}` (> {RSI_4H_THRESHOLD})\n"
                f"• *RSI (12h)*: `{rsi_12h}` (> {RSI_12H_THRESHOLD})\n"
                f"• *RSI (24h)*: `{rsi_24h}` (> {RSI_24H_THRESHOLD})\n"
            )
            send_telegram_alert(msg_short)

        # --- ĐIỀU KIỆN LONG (Nếu kích hoạt lại) ---
        elif (price_change >= PRICE_CHANGE_THRESHOLD_LONG and 
              rsi_4h > RSI_4H_THRESHOLD_LONG and 
              rsi_12h > RSI_12H_THRESHOLD_LONG and 
              rsi_24h > RSI_24H_THRESHOLD_LONG):
            
            candle_info = check_4h_candles(symbol)
            if not candle_info:
                time.sleep(0.3)
                continue

            change_n = candle_info["change_n"]
            change_prev = candle_info["change_prev"]
            current_price = candle_info["current_price"]

            open_4h_prev = candle_info["open_4h_prev"]
            high_4h_prev = candle_info["high_4h_prev"]
            low_4h_prev = candle_info["low_4h_prev"]
            close_4h_prev = candle_info["close_4h_prev"]
            
            tp_cur = current_price * 1.10
            sl_cur = low_4h_prev

            if change_n > 0 and change_prev != 0 and (change_n / abs(change_prev)) >= THRESHOLD_4H_RATIO:
                total_4h = round(change_n + change_prev, 2)
                ratio_4h = round(change_n / abs(change_prev), 2)

                candle_1h_info = check_1h_candles(symbol)
                change_n_1h = candle_1h_info["change_n"] if candle_1h_info else 0.0

                msg_long = (
                    f"⚡ *COIN ALERT THỎA ĐIỀU KIỆN LONG!*\n"
                    f"• *Symbol*: `{symbol}`\n"
                    f"• *Giá hiện tại*: `{fmt_price(current_price)}`\n"
                    f"• *Price Change (24h)*: `+{price_change:.2f}%` (>= {PRICE_CHANGE_THRESHOLD_LONG}%)\n"
                    f"• *RSI (4h)*: `{rsi_4h}` (> {RSI_4H_THRESHOLD_LONG})\n"
                    f"• *RSI (12h)*: `{rsi_12h}` (> {RSI_12H_THRESHOLD_LONG})\n"
                    f"• *RSI (24h)*: `{rsi_24h}` (> {RSI_24H_THRESHOLD_LONG})\n"
                    f"• *Nến 4h trước đó (n-1)*: `+{change_prev:.2f}%`\n"
                    f"   ▫️ O: `{fmt_price(open_4h_prev)}` | H: `{fmt_price(high_4h_prev)}`\n"
                    f"   ▫️ L: `{fmt_price(low_4h_prev)}` | C: `{fmt_price(close_4h_prev)}`\n"
                    f"• *Nến 4h hiện tại (n)*: `+{change_n:.2f}%`\n"
                    f"• *Tỷ lệ nến 4h n/abs(n-1)*: `{ratio_4h}x` (>= {THRESHOLD_4H_RATIO}x)\n"
                    f"• *Tổng tăng 2 nến 4h*: `+{total_4h:.2f}%`\n"
                    f"• *Nến 1h hiện tại (n)*: `{change_n_1h:+.2f}%`\n"
                    f"• *Take Profit (TP)*: `{fmt_price(tp_cur)}` (+10.0%)\n"
                    f"• *Stop Loss (SL)*: `{fmt_price(sl_cur)}`\n"
                )
                send_telegram_alert_long(msg_long)

        time.sleep(0.3)

    # =============================================================
    # NHÓM 2: CÁC COIN GIẢM GIÁ 24H <= -10% (SHORT ĐẢO CHIỀU TỪ ĐỈNH TUẦN N-1)
    # =============================================================
    matched_short_week_candidates = [
        t for t in tickers
        if isinstance(t, dict) and t.get("symbol", "").endswith("USDT") and float(t.get("priceChangePercent", 0)) <= PRICE_CHANGE_THRESHOLD_SHORT
    ]
    print(f"\n--- [Nhiệm vụ Short Week] Tìm thấy {len(matched_short_week_candidates)} coin có biến động 24h <= {PRICE_CHANGE_THRESHOLD_SHORT}% ---")

    for coin in matched_short_week_candidates:
        symbol = coin["symbol"]
        price = float(coin["lastPrice"])
        price_change = float(coin["priceChangePercent"])

        rsi_week_n, rsi_week_prev = get_binance_rsi_week_data(symbol)
        rsi_24h = get_binance_rsi(symbol, "1d")
        rsi_4h = get_binance_rsi(symbol, "4h")

        print(f"-> [Check Short Week] {symbol}: 24h = {price_change:.2f}%, RSI 1W (n-1) = {rsi_week_prev}, 1W (n) = {rsi_week_n}")

        # --- ĐIỀU KIỆN SHORT 2: Coin giảm <= -10% VÀ RSI tuần trước đó (n-1) > 93 ---
        if rsi_week_prev > RSI_SHORT_WEEK_THRESHOLD_UP:
            msg_short_reversal = (
                f"📉 *CẢNH BÁO SHORT (XÁC NHẬN ĐẢO CHIỀU TỪ ĐỈNH TUẦN N-1)!*\n"
                f"• *Symbol*: `{symbol}`\n"
                f"• *Giá hiện tại*: `{fmt_price(price)}`\n"
                f"• *Price Change (24h)*: `{price_change:.2f}%` (<= {PRICE_CHANGE_THRESHOLD_SHORT}%)\n"
                f"• *RSI Tuần trước đó (n-1)*: `{rsi_week_prev}` (> {RSI_SHORT_WEEK_THRESHOLD_UP})\n"
                f"• *RSI Tuần hiện tại (n)*: `{rsi_week_n}`\n"
                f"• *RSI (24h)*: `{rsi_24h}` | *4h*: `{rsi_4h}`\n"
            )
            send_telegram_alert_rsi_week(msg_short_reversal)

        time.sleep(0.3)

    # =============================================================
    # GỬI BÁO CÁO TRẠNG THÁI MỖI 30 PHÚT (:00 và :30)
    # =============================================================
    current_minute = datetime.now().minute
    if (current_minute % 30) < 3:
        print(f"-> [Gửi báo cáo] Đúng mốc 30 phút (phút hiện tại là :{current_minute:02d})")
        send_telegram_rsi_status(rsi_bot_status_msg)
    else:
        print(f"-> [Bỏ qua báo cáo] Phút hiện tại là :{current_minute:02d} (chỉ gửi vào mốc :00 và :30)")

if __name__ == "__main__":
    scan_market()
    print("\nQuét hoàn tất.")

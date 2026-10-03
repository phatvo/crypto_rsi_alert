import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# ================= CẤU HÌNH =================
GOOGLE_SHEET_WEBHOOK_URL = os.getenv(
    "GOOGLE_SHEET_WEBHOOK_URL"
)
TIMEFRAME = "4h"
CANDLE_LIMIT = 80             # 80 nến 4h (~13 ngày, đủ tính MACD 26, BB 20 và tìm đỉnh/đáy 5-35 nến)
KC_MULTIPLIER = 1.0           # Keltner Channels (KC 20 1 khớp với app Binance)
MIN_SWING_DISTANCE = 5        # Khoảng cách tối thiểu giữa 2 đỉnh/đáy
MAX_SWING_DISTANCE = 35       # Khoảng cách tối đa giữa 2 đỉnh/đáy
MAX_LEVEL_DIFF = 0.035        # Độ lệch tối đa giữa 2 đỉnh hoặc 2 đáy (<= 3.5%)
MIN_NECK_DEPTH = 0.03         # Độ sâu tối thiểu viền cổ (>= 3.0%)
RSI_WEEK_THRESHOLD = 80.0     # Ngưỡng RSI tuần quá mua


def append_to_sheet(payload: dict) -> str:
    """Gửi dữ liệu tín hiệu mới về Google Sheet Webhook"""
    if not GOOGLE_SHEET_WEBHOOK_URL:
        return "Thiếu WEBHOOK_URL"
    try:
        resp = requests.post(GOOGLE_SHEET_WEBHOOK_URL, json=payload, timeout=10)
        status = resp.text.strip()
        return status
    except Exception as e:
        return f"Lỗi: {e}"


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Tính các chỉ báo kỹ thuật: RSI, Bollinger Bands, Keltner Channels, Squeeze, MACD, Volume MA"""
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']

    # 1. RSI (14)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -1 * delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = round(100 - (100 / (1 + rs)), 2)

    # 2. Bollinger Bands (20, 2)
    df['BB_Mid'] = close.rolling(window=20).mean()
    bb_std = close.rolling(window=20).std()
    df['BB_Upper'] = df['BB_Mid'] + (bb_std * 2.0)
    df['BB_Lower'] = df['BB_Mid'] - (bb_std * 2.0)

    # 3. Keltner Channels (EMA 20, ATR 10, Multiplier 1.0)
    df['KC_Mid'] = close.ewm(span=20, adjust=False).mean()
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=10).mean()
    df['KC_Upper'] = df['KC_Mid'] + (atr * KC_MULTIPLIER)
    df['KC_Lower'] = df['KC_Mid'] - (atr * KC_MULTIPLIER)

    # 4. Trạng thái TTM Squeeze
    df['Is_Squeeze'] = (df['BB_Lower'] > df['KC_Lower']) & (df['BB_Upper'] < df['KC_Upper'])
    df['Squeeze_Fired'] = (~df['Is_Squeeze']) & (df['Is_Squeeze'].shift(1) == True)

    # 5. MACD (12, 26, 9)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    # 6. Volume MA20 & Volume Breakout
    df['Vol_MA20'] = volume.rolling(window=20).mean()
    df['Vol_Ratio'] = round(volume / df['Vol_MA20'], 2)
    df['Vol_Breakout'] = volume > (df['Vol_MA20'] * 1.5)

    return df


def get_weekly_rsi_data(symbol: str) -> tuple:
    """Lấy RSI khung tuần (1W) của nến hiện tại (n) và nến trước đó (n-1)"""
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": "1w", "limit": 30}
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
    except Exception:
        return 0.0, 0.0


def scan_latest_candle(symbol: str) -> list:
    """
    Quét và kiểm tra xem ở nến 4h mới nhất có hình thành các mô hình:
    1. Bung nén TTM Squeeze (SQUEEZE_FIRED)
    2. Breakout viền cổ mô hình W (Double Bottom)
    3. Breakdown viền cổ mô hình M (Double Top)
    4. Bắt đỉnh tuần hoặc Gãy đỉnh tuần RSI >= 80
    """
    detected = []
    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": TIMEFRAME, "limit": CANDLE_LIMIT}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 50:
            return detected

        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"
        ])
        df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        df = calculate_indicators(df)
        n = len(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        curr_close = curr['close']
        prev_close = prev['close']
        time_str = str(curr['datetime'])

        highs = df['high'].values
        lows = df['low'].values

        # -------------------------------------------------------------
        # 1. KIỂM TRA BUNG NÉN TTM SQUEEZE TẠI NẾN HIỆN TẠI
        # -------------------------------------------------------------
        if curr['Squeeze_Fired'] and curr['Vol_Breakout']:
            direction = "TĂNG" if curr['MACD_Hist'] > 0 else "GIẢM"
            rsi_week_n, _ = get_weekly_rsi_data(symbol)
            payload = {
                "symbol": symbol,
                "time": time_str,
                "signal_type": f"SQUEEZE_FIRED_{direction}",
                "trigger_price": curr_close,
                "neckline_price": round(curr['BB_Mid'], 4),
                "rsi_weekly": rsi_week_n,
                "rsi_current": curr['RSI'],
                "macd_hist": round(curr['MACD_Hist'], 4),
                "is_squeeze": False,
                "vol_ratio": f"{curr['Vol_Ratio']}x",
                "notes": f"Bung nén Bollinger trong Keltner (KC 20 1) hướng {direction}. Vol: {curr['Vol_Ratio']}x"
            }
            sheet_res = append_to_sheet(payload)
            print(f"\n🎯 [PHÁT HIỆN SQUEEZE] {symbol} -> Bung nén hướng {direction} | Giá: {curr_close} | Vol: {curr['Vol_Ratio']}x | Sheet: {sheet_res}")
            detected.append(payload)

        # -------------------------------------------------------------
        # XÁC ĐỊNH CÁC ĐỈNH/ĐÁY SWING (CHO MÔ HÌNH W & M)
        # -------------------------------------------------------------
        k = 3
        is_peak = [False] * n
        is_trough = [False] * n
        for i in range(k, n - k):
            if all(highs[i] >= highs[i - j] for j in range(1, k + 1)) and all(highs[i] >= highs[i + j] for j in range(1, k + 1)):
                is_peak[i] = True
            if all(lows[i] <= lows[i - j] for j in range(1, k + 1)) and all(lows[i] <= lows[i + j] for j in range(1, k + 1)):
                is_trough[i] = True

        latest_idx = n - 1

        # -------------------------------------------------------------
        # 2. KIỂM TRA BREAKOUT VIỀN CỔ W (DOUBLE BOTTOM)
        # -------------------------------------------------------------
        recent_troughs = [idx for idx in range(latest_idx - MAX_SWING_DISTANCE, latest_idx) if idx >= 0 and is_trough[idx]]
        if len(recent_troughs) >= 2:
            t1, t2 = recent_troughs[-2], recent_troughs[-1]
            dist = t2 - t1
            if MIN_SWING_DISTANCE <= dist <= MAX_SWING_DISTANCE:
                l1, l2 = lows[t1], lows[t2]
                if abs(l1 - l2) / min(l1, l2) <= MAX_LEVEL_DIFF:
                    middle_peaks = [idx for idx in range(t1 + 1, t2) if is_peak[idx]]
                    if middle_peaks:
                        p_neck = max(middle_peaks, key=lambda idx: highs[idx])
                        neck_price = highs[p_neck]
                        if (neck_price - max(l1, l2)) / max(l1, l2) >= MIN_NECK_DEPTH:
                            if prev_close <= neck_price and curr_close > neck_price:
                                rsi_div = "Phân kỳ RSI (+)" if df['RSI'].iloc[t2] > df['RSI'].iloc[t1] else "Không phân kỳ"
                                rsi_week_n, _ = get_weekly_rsi_data(symbol)
                                payload = {
                                    "symbol": symbol,
                                    "time": time_str,
                                    "signal_type": "W_DOUBLE_BOTTOM",
                                    "trigger_price": curr_close,
                                    "neckline_price": neck_price,
                                    "rsi_weekly": rsi_week_n,
                                    "rsi_current": curr['RSI'],
                                    "macd_hist": round(curr['MACD_Hist'], 4),
                                    "is_squeeze": curr['Is_Squeeze'],
                                    "vol_ratio": f"{curr['Vol_Ratio']}x",
                                    "notes": f"Breakout viền cổ W. {rsi_div}. Vol: {curr['Vol_Ratio']}x"
                                }
                                sheet_res = append_to_sheet(payload)
                                print(f"\n🚀 [PHÁT HIỆN MÔ HÌNH W] {symbol} -> Breakout viền cổ: {neck_price} | Giá: {curr_close} | {rsi_div} | Sheet: {sheet_res}")
                                detected.append(payload)

        # -------------------------------------------------------------
        # 3. KIỂM TRA BREAKDOWN VIỀN CỔ M (DOUBLE TOP)
        # -------------------------------------------------------------
        recent_peaks = [idx for idx in range(latest_idx - MAX_SWING_DISTANCE, latest_idx) if idx >= 0 and is_peak[idx]]
        if len(recent_peaks) >= 2:
            p1, p2 = recent_peaks[-2], recent_peaks[-1]
            dist = p2 - p1
            if MIN_SWING_DISTANCE <= dist <= MAX_SWING_DISTANCE:
                h1, h2 = highs[p1], highs[p2]
                if abs(h1 - h2) / min(h1, h2) <= MAX_LEVEL_DIFF:
                    middle_troughs = [idx for idx in range(p1 + 1, p2) if is_trough[idx]]
                    if middle_troughs:
                        t_neck = min(middle_troughs, key=lambda idx: lows[idx])
                        neck_price = lows[t_neck]
                        if (min(h1, h2) - neck_price) / neck_price >= MIN_NECK_DEPTH:
                            if prev_close >= neck_price and curr_close < neck_price:
                                rsi_div = "Phân kỳ RSI (-)" if df['RSI'].iloc[p2] < df['RSI'].iloc[p1] else "Không phân kỳ"
                                rsi_week_n, _ = get_weekly_rsi_data(symbol)
                                payload = {
                                    "symbol": symbol,
                                    "time": time_str,
                                    "signal_type": "M_DOUBLE_TOP",
                                    "trigger_price": curr_close,
                                    "neckline_price": neck_price,
                                    "rsi_weekly": rsi_week_n,
                                    "rsi_current": curr['RSI'],
                                    "macd_hist": round(curr['MACD_Hist'], 4),
                                    "is_squeeze": curr['Is_Squeeze'],
                                    "vol_ratio": f"{curr['Vol_Ratio']}x",
                                    "notes": f"Breakdown viền cổ M. {rsi_div}. Vol: {curr['Vol_Ratio']}x"
                                }
                                sheet_res = append_to_sheet(payload)
                                print(f"\n⚠️ [PHÁT HIỆN MÔ HÌNH M] {symbol} -> Thủng viền cổ: {neck_price} | Giá: {curr_close} | {rsi_div} | Sheet: {sheet_res}")
                                detected.append(payload)

        # -------------------------------------------------------------
        # 4. KIỂM TRA ĐỈNH TUẦN QUÁ MUA HOẶC XÁC NHẬN GÃY ĐỈNH TUẦN
        # -------------------------------------------------------------
        candle_change = ((curr_close - prev_close) / prev_close) * 100
        if candle_change <= -5.0 or curr['RSI'] >= 75.0:
            rsi_week_n, rsi_week_prev = get_weekly_rsi_data(symbol)
            if rsi_week_prev >= RSI_WEEK_THRESHOLD and candle_change <= -8.0:
                payload = {
                    "symbol": symbol,
                    "time": time_str,
                    "signal_type": "WEEKLY_RSI_REVERSAL_BREAKDOWN",
                    "trigger_price": curr_close,
                    "neckline_price": round(curr['BB_Mid'], 4),
                    "rsi_weekly": rsi_week_prev,
                    "rsi_current": curr['RSI'],
                    "macd_hist": round(curr['MACD_Hist'], 4),
                    "is_squeeze": curr['Is_Squeeze'],
                    "vol_ratio": f"{curr['Vol_Ratio']}x",
                    "notes": f"Xác nhận gãy đỉnh tuần: RSI tuần n-1={rsi_week_prev}>={RSI_WEEK_THRESHOLD}, nến giảm {candle_change:.2f}%"
                }
                sheet_res = append_to_sheet(payload)
                print(f"\n📉 [GÃY ĐỈNH TUẦN] {symbol} -> RSI tuần n-1: {rsi_week_prev} | Nến 4h giảm: {candle_change:.2f}% | Sheet: {sheet_res}")
                detected.append(payload)

        return detected
    except Exception as e:
        print(f"Lỗi quét {symbol}: {e}")
        return detected


def main():
    print("=" * 70)
    print(f"🚀 KHỞI ĐỘNG SCAN_PATTERNS_HOURLY.PY (MỐC 1 GIỜ)")
    print(f"⏰ Thời gian bắt đầu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 Mục tiêu: Quét nến 4h mới nhất tìm mô hình W, M, Squeeze & Đỉnh tuần")
    print("=" * 70)

    try:
        tickers = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=15).json()
        symbols = [t['symbol'] for t in tickers if isinstance(t, dict) and t.get('symbol', '').endswith('USDT')]
    except Exception as e:
        print(f"❌ Lỗi lấy danh sách coin từ Binance: {e}")
        return

    total_coins = len(symbols)
    print(f"-> Đã lấy được danh sách {total_coins} cặp USDT từ Binance API.")
    print("-> Bắt đầu tiến trình phân tích kỹ thuật...")

    all_signals = []
    start_time = time.time()

    for idx, sym in enumerate(symbols, 1):
        sigs = scan_latest_candle(sym)
        if sigs:
            all_signals.extend(sigs)

        # In tiến độ định kỳ mỗi 50 coin
        if idx % 50 == 0 or idx == total_coins:
            print(f"   [Tiến độ: {idx:3d}/{total_coins}] Đã phân tích xong {idx} coin... (Phát hiện: {len(all_signals)} tín hiệu)")
        time.sleep(0.04)

    elapsed = round(time.time() - start_time, 1)

    print("\n" + "=" * 70)
    print(f"📊 BÁO CÁO TỔNG KẾT QUÉT MÔ HÌNH HÀNG GIỜ")
    print(f"⏱ Thời gian thực thi: {elapsed} giây (~{elapsed/60:.1f} phút)")
    print(f"📈 Tổng số coin đã quét: {total_coins} cặp USDT")
    print(f"🔔 Tổng số tín hiệu đạt chuẩn phát hiện được: {len(all_signals)}")

    if all_signals:
        print("\n📋 Danh sách tín hiệu vừa ghi nhận:")
        for s in all_signals:
            print(f"   • {s['symbol']} | {s['signal_type']} | Giá: {s['trigger_price']} | {s['notes']}")
    else:
        print("ℹ️ Kết quả: Không có cặp coin nào xuất hiện điểm breakout mô hình ở nến 4h hiện tại.")
    print("=" * 70)


if __name__ == "__main__":
    main()

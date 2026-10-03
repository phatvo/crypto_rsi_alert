#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SCAN_PATTERNS_HOURLY.PY (HỖ TRỢ ĐA KHUNG THỜI GIAN: 12H VÀ 1D + TÍCH HỢP TOÀN DIỆN RSI TUẦN)
Tối ưu cho lịch quét:
- Ca sáng (07:10 - 08:00 VN): Tự động quét cả khung 1 Ngày (1D) và 12 Giờ (12h ca đêm vừa đóng).
- Ca tối (19:10 - 20:00 VN): Tự động quét khung 12 Giờ (12h ca ngày vừa đóng).
- Đã khắc phục lỗi: Tự động ép kiểu NumPy (np.bool_, np.floating, np.integer) sang kiểu Python chuẩn để tránh lỗi JSON serializable.
"""

import os
import sys
import time
import argparse
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

# ================= CẤU HÌNH GOOGLE SHEET WEBHOOK =================
GOOGLE_SHEET_WEBHOOK_URL = os.getenv(
    "GOOGLE_SHEET_WEBHOOK_URL",
    "https://script.google.com/macros/s/AKfycbxuZEvS0V43a0E5mATuBpGy95cx4S9h7X02JL494cXL8Ncuy_GBioy5q056U_0FQio39A/exec"
)

# ================= CẤU HÌNH THAM SỐ THEO TỪNG KHUNG THỜI GIAN =================
TIMEFRAME_CONFIGS = {
    "12h": {
        "candle_limit": 80,          # 80 nến 12h (~40 ngày lịch sử)
        "min_swing_distance": 4,     # Tối thiểu 4 nến (48 tiếng) giữa 2 đỉnh/đáy
        "max_swing_distance": 25,    # Tối đa 25 nến (~12.5 ngày) giữa 2 đỉnh/đáy
        "max_level_diff": 0.040,     # Độ lệch tối đa giữa 2 đỉnh/đáy (<= 4.0%)
        "min_neck_depth": 0.035,     # Độ sâu viền cổ tối thiểu (>= 3.5%)
        "kc_multiplier": 1.0,
    },
    "1d": {
        "candle_limit": 80,          # 80 nến 1D (~80 ngày lịch sử)
        "min_swing_distance": 3,     # Tối thiểu 3 nến ngày (3 ngày) giữa 2 đỉnh/đáy
        "max_swing_distance": 20,    # Tối đa 20 nến ngày (~20 ngày) giữa 2 đỉnh/đáy
        "max_level_diff": 0.045,     # Độ lệch tối đa giữa 2 đỉnh/đáy (<= 4.5%)
        "min_neck_depth": 0.040,     # Độ sâu viền cổ tối thiểu (>= 4.0%)
        "kc_multiplier": 1.0,
    },
    "4h": {
        "candle_limit": 80,          # 80 nến 4h (~13 ngày)
        "min_swing_distance": 5,
        "max_swing_distance": 35,
        "max_level_diff": 0.035,
        "min_neck_depth": 0.030,
        "kc_multiplier": 1.0,
    }
}

# Ngưỡng RSI Tuần (1W)
RSI_WEEK_OVERBOUGHT = 80.0       # Ngưỡng cảnh báo đỉnh tuần quá mua (>= 80.0)
RSI_WEEK_CLIMAX = 90.0           # Ngưỡng đỉnh tuần cực đại (>= 90.0)
RSI_WEEK_BREAKDOWN_DROP = -7.0   # Mức giảm nến xác nhận gãy đỉnh tuần (<= -7.0%)


def get_current_vn_time() -> datetime:
    """Lấy thời gian hiện tại theo múi giờ Việt Nam (UTC+7)"""
    utc_now = datetime.now(timezone.utc)
    return utc_now + timedelta(hours=7)


def determine_timeframes(tf_arg: str) -> list:
    """Xác định danh sách khung thời gian cần quét"""
    if tf_arg and tf_arg.lower() != "auto":
        tfs = [t.strip().lower() for t in tf_arg.split(",")]
        if "both" in tfs:
            return ["12h", "1d"]
        return tfs

    vn_time = get_current_vn_time()
    hour = vn_time.hour
    if 7 <= hour < 12:
        return ["12h", "1d"]
    elif 19 <= hour < 24:
        return ["12h"]
    else:
        return ["12h", "1d"]


def sanitize_payload(obj):
    """Chuyển đổi triệt để các kiểu dữ liệu NumPy sang kiểu chuẩn của Python để tránh lỗi JSON serializable"""
    if isinstance(obj, dict):
        return {k: sanitize_payload(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_payload(v) for v in obj]
    elif isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    elif isinstance(obj, (np.integer, int)):
        return int(obj)
    elif isinstance(obj, (np.floating, float)):
        return float(obj)
    return obj


def append_to_sheet(payload: dict) -> str:
    """Gửi dữ liệu tín hiệu mới về Google Sheet Webhook"""
    if not GOOGLE_SHEET_WEBHOOK_URL:
        return "Thiếu WEBHOOK_URL"
    try:
        clean_payload = sanitize_payload(payload)
        resp = requests.post(GOOGLE_SHEET_WEBHOOK_URL, json=clean_payload, timeout=10)
        status = resp.text.strip()
        return status
    except Exception as e:
        return f"Lỗi: {e}"


def calculate_indicators(df: pd.DataFrame, kc_multiplier: float = 1.0) -> pd.DataFrame:
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

    # 3. Keltner Channels (EMA 20, ATR 10, Multiplier)
    df['KC_Mid'] = close.ewm(span=20, adjust=False).mean()
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=10).mean()
    df['KC_Upper'] = df['KC_Mid'] + (atr * kc_multiplier)
    df['KC_Lower'] = df['KC_Mid'] - (atr * kc_multiplier)

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


def scan_candle_for_timeframe(symbol: str, timeframe: str, check_closed_candle: bool = True) -> list:
    """
    Quét mô hình và kiểm tra toàn diện điều kiện RSI Tuần cho từng cặp coin.
    """
    detected = []
    cfg = TIMEFRAME_CONFIGS.get(timeframe.lower(), TIMEFRAME_CONFIGS["12h"])
    candle_limit = cfg["candle_limit"]
    min_swing = cfg["min_swing_distance"]
    max_swing = cfg["max_swing_distance"]
    max_level_diff = cfg["max_level_diff"]
    min_neck_depth = cfg["min_neck_depth"]
    kc_multiplier = cfg["kc_multiplier"]

    url = "https://data-api.binance.vision/api/v3/klines"
    params = {"symbol": symbol, "interval": timeframe, "limit": candle_limit}

    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if not isinstance(data, list) or len(data) < 40:
            return detected

        df = pd.DataFrame(data, columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "q_vol", "trades", "tb_base", "tb_quote", "ignore"
        ])
        df['datetime'] = pd.to_datetime(df['open_time'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        df = calculate_indicators(df, kc_multiplier=kc_multiplier)
        n = len(df)

        if check_closed_candle and n >= 3:
            curr_idx = n - 2
            prev_idx = n - 3
        else:
            curr_idx = n - 1
            prev_idx = n - 2

        curr = df.iloc[curr_idx]
        prev = df.iloc[prev_idx]
        curr_close = float(curr['close'])
        prev_close = float(prev['close'])
        time_str = str(curr['datetime'])
        tf_tag = timeframe.upper()

        highs = df['high'].values
        lows = df['low'].values

        # Lấy RSI Tuần để kết hợp vào mọi tín hiệu
        rsi_week_n, rsi_week_prev = get_weekly_rsi_data(symbol)

        # 1. KIỂM TRA BUNG NÉN TTM SQUEEZE
        if curr['Squeeze_Fired'] and curr['Vol_Breakout']:
            direction = "TĂNG" if curr['MACD_Hist'] > 0 else "GIẢM"
            note_week = f" [RSI 1W: {rsi_week_n}]"
            payload = {
                "symbol": symbol,
                "time": time_str,
                "signal_type": f"SQUEEZE_FIRED_{direction}_{tf_tag}",
                "trigger_price": curr_close,
                "neckline_price": float(round(curr['BB_Mid'], 4)),
                "rsi_weekly": float(rsi_week_n),
                "rsi_current": float(curr['RSI']),
                "macd_hist": float(round(curr['MACD_Hist'], 4)),
                "is_squeeze": False,
                "vol_ratio": f"{curr['Vol_Ratio']}x",
                "notes": f"[{tf_tag}] Bung nén Bollinger trong Keltner (KC 20 1) hướng {direction}. Vol: {curr['Vol_Ratio']}x.{note_week}"
            }
            sheet_res = append_to_sheet(payload)
            print(f"\n🎯 [SQUEEZE {tf_tag}] {symbol} -> Hướng {direction} | Giá: {curr_close} | Vol: {curr['Vol_Ratio']}x | RSI 1W: {rsi_week_n} | Sheet: {sheet_res}")
            detected.append(payload)

        # XÁC ĐỊNH ĐỈNH/ĐÁY SWING CHO MÔ HÌNH W & M
        k = 2 if timeframe in ["12h", "1d"] else 3
        is_peak = [False] * n
        is_trough = [False] * n
        for i in range(k, curr_idx - k + 1):
            if all(highs[i] >= highs[i - j] for j in range(1, k + 1)) and all(highs[i] >= highs[i + j] for j in range(1, k + 1)):
                is_peak[i] = True
            if all(lows[i] <= lows[i - j] for j in range(1, k + 1)) and all(lows[i] <= lows[i + j] for j in range(1, k + 1)):
                is_trough[i] = True

        latest_idx = curr_idx

        # 2. KIỂM TRA MÔ HÌNH W (DOUBLE BOTTOM) + LỌC RSI TUẦN
        recent_troughs = [idx for idx in range(latest_idx - max_swing, latest_idx) if idx >= 0 and is_trough[idx]]
        if len(recent_troughs) >= 2:
            t1, t2 = recent_troughs[-2], recent_troughs[-1]
            dist = t2 - t1
            if min_swing <= dist <= max_swing:
                l1, l2 = lows[t1], lows[t2]
                if abs(l1 - l2) / min(l1, l2) <= max_level_diff:
                    middle_peaks = [idx for idx in range(t1 + 1, t2) if is_peak[idx]]
                    if middle_peaks:
                        p_neck = max(middle_peaks, key=lambda idx: highs[idx])
                        neck_price = float(highs[p_neck])
                        if (neck_price - max(l1, l2)) / max(l1, l2) >= min_neck_depth:
                            if prev_close <= neck_price and curr_close > neck_price:
                                rsi_div = "Phân kỳ RSI (+)" if df['RSI'].iloc[t2] > df['RSI'].iloc[t1] else "Không phân kỳ"
                                
                                week_comment = ""
                                if rsi_week_n >= RSI_WEEK_OVERBOUGHT:
                                    week_comment = f" ⚠️ Cảnh báo: RSI tuần={rsi_week_n}>=80 (vùng đỉnh, đề phòng bull trap)"
                                elif rsi_week_n <= 35.0:
                                    week_comment = f" ⭐ RSI tuần={rsi_week_n}<=35 (vùng đáy hỗ trợ cực mạnh)"
                                else:
                                    week_comment = f" (RSI 1W: {rsi_week_n})"

                                payload = {
                                    "symbol": symbol,
                                    "time": time_str,
                                    "signal_type": f"W_DOUBLE_BOTTOM_{tf_tag}",
                                    "trigger_price": curr_close,
                                    "neckline_price": neck_price,
                                    "rsi_weekly": float(rsi_week_n),
                                    "rsi_current": float(curr['RSI']),
                                    "macd_hist": float(round(curr['MACD_Hist'], 4)),
                                    "is_squeeze": bool(curr['Is_Squeeze']),
                                    "vol_ratio": f"{curr['Vol_Ratio']}x",
                                    "notes": f"[{tf_tag}] Breakout viền cổ W. {rsi_div}. Vol: {curr['Vol_Ratio']}x.{week_comment}"
                                }
                                sheet_res = append_to_sheet(payload)
                                print(f"\n🚀 [MÔ HÌNH W {tf_tag}] {symbol} -> Breakout: {neck_price} | Giá: {curr_close} | {rsi_div} | RSI 1W: {rsi_week_n} | Sheet: {sheet_res}")
                                detected.append(payload)

        # 3. KIỂM TRA MÔ HÌNH M (DOUBLE TOP) + LỌC RSI TUẦN
        recent_peaks = [idx for idx in range(latest_idx - max_swing, latest_idx) if idx >= 0 and is_peak[idx]]
        if len(recent_peaks) >= 2:
            p1, p2 = recent_peaks[-2], recent_peaks[-1]
            dist = p2 - p1
            if min_swing <= dist <= max_swing:
                h1, h2 = highs[p1], highs[p2]
                if abs(h1 - h2) / min(h1, h2) <= max_level_diff:
                    middle_troughs = [idx for idx in range(p1 + 1, p2) if is_trough[idx]]
                    if middle_troughs:
                        t_neck = min(middle_troughs, key=lambda idx: lows[idx])
                        neck_price = float(lows[t_neck])
                        if (min(h1, h2) - neck_price) / neck_price >= min_neck_depth:
                            if prev_close >= neck_price and curr_close < neck_price:
                                rsi_div = "Phân kỳ RSI (-)" if df['RSI'].iloc[p2] < df['RSI'].iloc[p1] else "Không phân kỳ"
                                
                                week_comment = ""
                                if rsi_week_n >= RSI_WEEK_OVERBOUGHT:
                                    week_comment = f" ⭐ Thuận xu hướng lớn: RSI tuần={rsi_week_n}>=80 (vùng đỉnh xả mạnh)"
                                else:
                                    week_comment = f" (RSI 1W: {rsi_week_n})"

                                payload = {
                                    "symbol": symbol,
                                    "time": time_str,
                                    "signal_type": f"M_DOUBLE_TOP_{tf_tag}",
                                    "trigger_price": curr_close,
                                    "neckline_price": neck_price,
                                    "rsi_weekly": float(rsi_week_n),
                                    "rsi_current": float(curr['RSI']),
                                    "macd_hist": float(round(curr['MACD_Hist'], 4)),
                                    "is_squeeze": bool(curr['Is_Squeeze']),
                                    "vol_ratio": f"{curr['Vol_Ratio']}x",
                                    "notes": f"[{tf_tag}] Breakdown viền cổ M. {rsi_div}. Vol: {curr['Vol_Ratio']}x.{week_comment}"
                                }
                                sheet_res = append_to_sheet(payload)
                                print(f"\n⚠️ [MÔ HÌNH M {tf_tag}] {symbol} -> Thủng viền cổ: {neck_price} | Giá: {curr_close} | {rsi_div} | RSI 1W: {rsi_week_n} | Sheet: {sheet_res}")
                                detected.append(payload)

        # 4. ĐIỀU KIỆN RSI TUẦN: BẮT ĐỈNH QUÁ MUA (WEEKLY_RSI_OVERBOUGHT_PEAK)
        if rsi_week_n >= RSI_WEEK_OVERBOUGHT:
            climax_tag = " [CỰC ĐẠI >= 90]" if rsi_week_n >= RSI_WEEK_CLIMAX else ""
            payload_peak = {
                "symbol": symbol,
                "time": time_str,
                "signal_type": f"WEEKLY_RSI_OVERBOUGHT_PEAK_{tf_tag}",
                "trigger_price": curr_close,
                "neckline_price": float(round(curr['BB_Mid'], 4)),
                "rsi_weekly": float(rsi_week_n),
                "rsi_current": float(curr['RSI']),
                "macd_hist": float(round(curr['MACD_Hist'], 4)),
                "is_squeeze": bool(curr['Is_Squeeze']),
                "vol_ratio": f"{curr['Vol_Ratio']}x",
                "notes": f"[{tf_tag}] Bắt đỉnh tuần quá mua{climax_tag}: RSI 1W = {rsi_week_n} >= {RSI_WEEK_OVERBOUGHT}. Vùng Short tiềm năng."
            }
            sheet_res = append_to_sheet(payload_peak)
            print(f"\n🚨 [ĐỈNH TUẦN QUÁ MUA {tf_tag}] {symbol} -> RSI 1W: {rsi_week_n} >= {RSI_WEEK_OVERBOUGHT} | Giá: {curr_close} | Sheet: {sheet_res}")
            detected.append(payload_peak)

        # 5. ĐIỀU KIỆN RSI TUẦN: XÁC NHẬN GÃY ĐỈNH TUẦN (WEEKLY_RSI_REVERSAL_BREAKDOWN)
        candle_change = ((curr_close - prev_close) / prev_close) * 100
        if rsi_week_prev >= RSI_WEEK_OVERBOUGHT and candle_change <= RSI_WEEK_BREAKDOWN_DROP:
            payload_breakdown = {
                "symbol": symbol,
                "time": time_str,
                "signal_type": f"WEEKLY_RSI_REVERSAL_BREAKDOWN_{tf_tag}",
                "trigger_price": curr_close,
                "neckline_price": float(round(curr['BB_Mid'], 4)),
                "rsi_weekly": float(rsi_week_prev),
                "rsi_current": float(curr['RSI']),
                "macd_hist": float(round(curr['MACD_Hist'], 4)),
                "is_squeeze": bool(curr['Is_Squeeze']),
                "vol_ratio": f"{curr['Vol_Ratio']}x",
                "notes": f"[{tf_tag}] Xác nhận gãy đỉnh tuần: RSI tuần n-1 = {rsi_week_prev} >= {RSI_WEEK_OVERBOUGHT}, nến giảm {candle_change:.2f}%."
            }
            sheet_res = append_to_sheet(payload_breakdown)
            print(f"\n📉 [GÃY ĐỈNH TUẦN {tf_tag}] {symbol} -> RSI tuần n-1: {rsi_week_prev} | Nến giảm: {candle_change:.2f}% | Sheet: {sheet_res}")
            detected.append(payload_breakdown)

        return detected
    except Exception as e:
        print(f"Lỗi quét {symbol} [{timeframe}]: {e}")
        return detected


def main():
    parser = argparse.ArgumentParser(description="Bot quét mô hình giá Binance đa khung thời gian (12h, 1D) kết hợp RSI Tuần")
    parser.add_argument("--tf", "--timeframe", dest="timeframe", default=os.getenv("TIMEFRAME", "auto"),
                        help="Khung thời gian quét: '12h', '1d', 'both' (cả 12h và 1d), '4h', hoặc 'auto' (tự động theo giờ VN)")
    parser.add_argument("--live", action="store_true", default=False,
                        help="Nếu bật --live: Quét nến đang chạy dở (iloc[-1]). Mặc định: Quét nến vừa đóng hoàn tất (iloc[-2]).")
    args = parser.parse_args()

    check_closed = not args.live
    target_timeframes = determine_timeframes(args.timeframe)
    vn_now_str = get_current_vn_time().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 75)
    print("🚀 KHỞI ĐỘNG SCAN_PATTERNS_HOURLY.PY (12H & 1D + RSI TUẦN)")
    print(f"⏰ Giờ Việt Nam hiện tại: {vn_now_str}")
    print(f"🎯 Khung thời gian quét: {', '.join([tf.upper() for tf in target_timeframes])}")
    print(f"📌 Chế độ nến: {'NẾN VỪA ĐÓNG HOÀN TẤT (iloc[-2], chuẩn xác không repaint)' if check_closed else 'NẾN ĐANG CHẠY (iloc[-1])'}")
    print(f"📊 Bộ lọc RSI Tuần: Bắt đỉnh quá mua >= {RSI_WEEK_OVERBOUGHT} & Xác nhận gãy nến <= {RSI_WEEK_BREAKDOWN_DROP}%")
    print("=" * 75)

    try:
        tickers = requests.get("https://data-api.binance.vision/api/v3/ticker/24hr", timeout=15).json()
        symbols = [t['symbol'] for t in tickers if isinstance(t, dict) and t.get('symbol', '').endswith('USDT')]
    except Exception as e:
        print(f"❌ Lỗi lấy danh sách coin từ Binance: {e}")
        return

    total_coins = len(symbols)
    print(f"-> Đã lấy được danh sách {total_coins} cặp USDT từ Binance API.")
    print("-> Bắt đầu tiến trình phân tích kỹ thuật...")

    all_signals_by_tf = {tf: [] for tf in target_timeframes}
    start_time = time.time()

    for idx, sym in enumerate(symbols, 1):
        for tf in target_timeframes:
            sigs = scan_candle_for_timeframe(sym, timeframe=tf, check_closed_candle=check_closed)
            if sigs:
                all_signals_by_tf[tf].extend(sigs)

        if idx % 50 == 0 or idx == total_coins:
            total_found = sum(len(v) for v in all_signals_by_tf.values())
            print(f"   [Tiến độ: {idx:3d}/{total_coins}] Đã phân tích xong {idx} coin... (Phát hiện: {total_found} tín hiệu)")
        time.sleep(0.04)

    elapsed = round(time.time() - start_time, 1)

    print("\n" + "=" * 75)
    print("📊 BÁO CÁO TỔNG KẾT QUÉT MÔ HÌNH & RSI TUẦN")
    print(f"⏱ Thời gian thực thi: {elapsed} giây (~{elapsed/60:.1f} phút)")
    print(f"📈 Tổng số coin đã quét: {total_coins} cặp USDT")
    
    total_signals = sum(len(v) for v in all_signals_by_tf.values())
    print(f"🔔 Tổng số tín hiệu đạt chuẩn phát hiện được: {total_signals}")

    if total_signals > 0:
        for tf, sig_list in all_signals_by_tf.items():
            print(f"\n📋 Danh sách tín hiệu khung [{tf.upper()}] ({len(sig_list)} tín hiệu):")
            if not sig_list:
                print("   (Không có tín hiệu)")
            for s in sig_list:
                print(f"   • {s['symbol']} | {s['signal_type']} | Giá: {s['trigger_price']} | {s['notes']}")
    else:
        print("ℹ️ Kết quả: Không có cặp coin nào xuất hiện điểm breakout mô hình ở các khung quét.")
    print("=" * 75)


if __name__ == "__main__":
    main()

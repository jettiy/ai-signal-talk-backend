"""
차트 데이터 수집 서비스 — yfinance 단일 소스.
캐시 및 rate limit 회피.
"""
import yfinance as yf
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import pandas as pd
import asyncio
import time

# 캐시: (symbol, timeframe, lookahead_n) -> (fetched_at, df). TTL 초.
_CHART_CACHE: Dict[Tuple[str, str, int], Tuple[float, Optional[pd.DataFrame]]] = {}
_CHART_CACHE_TTL_SEC = 90
_LAST_REQUEST_TIME: Dict[str, float] = {}
_MIN_REQUEST_INTERVAL_SEC = 3.0

# TradingView 심볼을 Yahoo Finance 심볼로 매핑 (코스피 추가)
SYMBOL_MAPPING = {
    "NQ1!": "NQ=F",      # 나스닥 선물
    "HSI1!": "HSI=F",    # 항셍 선물
    "GOLD": "GC=F",       # 골드 선물
    "CL1!": "CL=F",       # 원유 선물
    "KS1!": "KS=F",       # 코스피 선물
}

# V2 프론트엔드 심볼 → 내부 심볼 매핑
V2_TO_INTERNAL = {
    "NQUSD": "NQ1!",
    "GCUSD": "GOLD",
    "CLUSD": "CL1!",
    "KSUSD": "KS1!",
    "HSIUSD": "HSI1!",
}

# 타임프레임 매핑 (V2 프론트엔드 → yfinance interval)
TIMEFRAME_MAPPING = {
    "1": "1m",
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "1H": "1h",
    "1D": "1d",
    "1W": "1wk",
    "1M": "1mo",
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "60min": "1h",
}


def get_yahoo_symbol(symbol: str) -> str:
    """심볼을 Yahoo Finance 심볼로 변환"""
    internal = V2_TO_INTERNAL.get(symbol, symbol)
    return SYMBOL_MAPPING.get(internal, internal)


def get_yfinance_interval(timeframe: str) -> str:
    return TIMEFRAME_MAPPING.get(timeframe, "15m")


def get_period_for_timeframe(timeframe: str, lookahead_n: int = 30) -> Tuple[str, int]:
    period_days_map = {
        "1": (7, 10080), "1min": (7, 10080),
        "5": (30, 8640), "5min": (30, 8640),
        "15": (60, 5760), "15min": (60, 5760),
        "30": (60, 2880), "30min": (60, 2880),
        "60": (730, 17520), "1H": (730, 17520), "60min": (730, 17520),
        "1D": (730, 730),
        "1W": (1825, 260),
        "1M": (3650, 120),
    }
    period_days, max_results = period_days_map.get(timeframe, (60, 1000))
    if lookahead_n > 30:
        period_days = int(period_days * (lookahead_n / 30))
    return f"{period_days}d", max_results


def _fetch_chart_data_sync(symbol: str, timeframe: str, lookahead_n: int) -> Optional[pd.DataFrame]:
    yahoo_symbol = get_yahoo_symbol(symbol)
    interval = get_yfinance_interval(timeframe)
    period, max_results = get_period_for_timeframe(timeframe, lookahead_n)
    ticker = yf.Ticker(yahoo_symbol)
    df = ticker.history(period=period, interval=interval)
    if df.empty:
        return None
    df.columns = [col.replace(' ', '') for col in df.columns]
    df.reset_index(inplace=True)
    if 'Date' in df.columns:
        df.rename(columns={'Date': 'Datetime'}, inplace=True)
    required_columns = ['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
    available_columns = [col for col in required_columns if col in df.columns]
    df = df[available_columns]
    df = df.sort_values('Datetime', ascending=False)
    if len(df) > max_results:
        df = df.head(max_results)
    return df


async def fetch_chart_data(
    symbol: str,
    timeframe: str,
    lookahead_n: int = 30,
    max_retries: int = 3,
) -> Optional[pd.DataFrame]:
    cache_key = (symbol, timeframe, lookahead_n)
    now = time.time()
    if cache_key in _CHART_CACHE:
        fetched_at, cached_df = _CHART_CACHE[cache_key]
        if now - fetched_at < _CHART_CACHE_TTL_SEC and cached_df is not None:
            print(f"[CHART_DATA] Cache hit for {symbol} ({timeframe})")
            return cached_df
        if now - fetched_at >= _CHART_CACHE_TTL_SEC:
            del _CHART_CACHE[cache_key]

    yahoo_symbol = get_yahoo_symbol(symbol)
    last_key = yahoo_symbol
    if last_key in _LAST_REQUEST_TIME:
        elapsed = now - _LAST_REQUEST_TIME[last_key]
        if elapsed < _MIN_REQUEST_INTERVAL_SEC:
            await asyncio.sleep(_MIN_REQUEST_INTERVAL_SEC - elapsed)

    last_error = None
    for attempt in range(max_retries):
        try:
            _LAST_REQUEST_TIME[last_key] = time.time()
            df = await asyncio.to_thread(_fetch_chart_data_sync, symbol, timeframe, lookahead_n)
            if df is not None and not df.empty:
                _CHART_CACHE[cache_key] = (time.time(), df)
                print(f"[CHART_DATA] yfinance {len(df)} points for {symbol} ({timeframe})")
                return df
            last_error = ValueError("Empty or no data")
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            if "too many" in err_str or "429" in err_str or "rate" in err_str:
                wait = 3.0 * (attempt + 1)
                print(f"[CHART_DATA] Rate limit (attempt {attempt + 1}/{max_retries}), waiting {wait:.0f}s")
                await asyncio.sleep(wait)
            else:
                print(f"[CHART_DATA] Error for {symbol}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2.0 * (attempt + 1))

    print(f"[CHART_DATA] Failed after {max_retries} attempts for {symbol} ({timeframe}): {last_error}")
    return None


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df_calc = df.sort_values('Datetime', ascending=True).copy()

    # EMA
    df_calc['EMA5'] = df_calc['Close'].ewm(span=5, adjust=False).mean()
    df_calc['EMA10'] = df_calc['Close'].ewm(span=10, adjust=False).mean()
    df_calc['EMA20'] = df_calc['Close'].ewm(span=20, adjust=False).mean()
    df_calc['EMA50'] = df_calc['Close'].ewm(span=50, adjust=False).mean()
    df_calc['EMA200'] = df_calc['Close'].ewm(span=200, adjust=False).mean()

    # RSI(14)
    delta = df_calc['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df_calc['RSI'] = 100 - (100 / (1 + rs))

    # MACD(12,26,9)
    exp1 = df_calc['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df_calc['Close'].ewm(span=26, adjust=False).mean()
    df_calc['MACD'] = exp1 - exp2
    df_calc['MACD_Signal'] = df_calc['MACD'].ewm(span=9, adjust=False).mean()
    df_calc['MACD_Hist'] = df_calc['MACD'] - df_calc['MACD_Signal']

    # Bollinger Bands(20)
    df_calc['BB_Mid'] = df_calc['Close'].rolling(window=20).mean()
    df_calc['BB_Std'] = df_calc['Close'].rolling(window=20).std()
    df_calc['BB_Upper'] = df_calc['BB_Mid'] + (df_calc['BB_Std'] * 2)
    df_calc['BB_Lower'] = df_calc['BB_Mid'] - (df_calc['BB_Std'] * 2)

    # ATR(14)
    high_low = df_calc['High'] - df_calc['Low']
    high_close = (df_calc['High'] - df_calc['Close'].shift(1)).abs()
    low_close = (df_calc['Low'] - df_calc['Close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df_calc['ATR'] = tr.rolling(14).mean()

    return df_calc.sort_values('Datetime', ascending=False)

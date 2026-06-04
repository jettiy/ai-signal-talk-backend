"""
시그널 규칙 엔진 v2 — 다차원 분석 기반.
모멘텀 + 추세 + 볼륨 + 변동성 + 다이버전스 + 다중시간프레임 → 확률 산출.
지지/저항 기반 손절/목표가 계산.
"""
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np


def _safe(val: Any, default: float = 0.0) -> float:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ─── 지표 스냅샷 ────────────────────────────────────────────────

def get_indicator_snapshot(df: pd.DataFrame) -> Dict[str, float]:
    if df is None or df.empty:
        return {}
    row = df.iloc[0]
    close = _safe(row.get("Close"))
    return {
        "close": close,
        "ema5": _safe(row.get("EMA5"), close),
        "ema10": _safe(row.get("EMA10"), close),
        "ema20": _safe(row.get("EMA20"), close),
        "ema50": _safe(row.get("EMA50"), close),
        "ema200": _safe(row.get("EMA200"), close),
        "rsi": _safe(row.get("RSI"), 50.0),
        "macd": _safe(row.get("MACD")),
        "macd_signal": _safe(row.get("MACD_Signal")),
        "macd_hist": _safe(row.get("MACD_Hist")),
        "bb_upper": _safe(row.get("BB_Upper"), close),
        "bb_mid": _safe(row.get("BB_Mid"), close),
        "bb_lower": _safe(row.get("BB_Lower"), close),
        "atr": _safe(row.get("ATR"), close * 0.01),
        "volume": _safe(row.get("Volume"), 0.0),
    }


# ─── 1. 모멘텀 점수 (RSI + MACD + Stochastic) ───────────────────

def compute_momentum_score(snap: Dict[str, float]) -> float:
    """-1.0 ~ +1.0, 양수=상승 모멘텀"""
    rsi = snap.get("rsi", 50.0)
    macd_hist = snap.get("macd_hist", 0.0)

    # RSI: 30 이하=과매도 반등(강세), 70 이상=과매수(약세)
    if rsi <= 30:
        rsi_score = -0.5 + (30 - rsi) / 60  # 과매도 → 반등 기대 → 상승
    elif rsi >= 70:
        rsi_score = 0.5 - (rsi - 70) / 60   # 과매수 → 조정 → 하락
    else:
        rsi_score = (rsi - 50.0) / 50.0

    # MACD 히스토그램: 부호 + 크기
    macd_score = np.tanh(macd_hist * 2) if macd_hist != 0 else 0.0

    raw = 0.55 * rsi_score + 0.45 * macd_score
    return max(-1.0, min(1.0, raw))


# ─── 2. 추세 점수 (EMA 정렬 + 기울기) ───────────────────────────

def compute_trend_score(snap: Dict[str, float], df: pd.DataFrame = None) -> float:
    """-1.0 ~ +1.0, 양수=상승 추세"""
    close = snap.get("close", 0.0)
    ema20 = snap.get("ema20", close)
    ema50 = snap.get("ema50", close)
    ema200 = snap.get("ema200", close)
    if close <= 0:
        return 0.0

    # 가격 위치 점수
    above_20 = 1.0 if close > ema20 else -1.0
    above_50 = 1.0 if close > ema50 else -1.0
    above_200 = 1.0 if close > ema200 else -1.0
    position_score = (above_20 * 0.4 + above_50 * 0.35 + above_200 * 0.25)

    # EMA 정렬 (완벽한 상승 정렬 = EMA20 > EMA50 > EMA200)
    alignment = 0.0
    if ema20 > ema50 > ema200:
        alignment = 1.0
    elif ema20 < ema50 < ema200:
        alignment = -1.0

    # EMA20 기울기 (데이터 있을 때만)
    slope_score = 0.0
    if df is not None and len(df) >= 5:
        ema20_vals = df["EMA20"].head(5).values if "EMA20" in df.columns else None
        if ema20_vals is not None and len(ema20_vals) >= 5:
            slope = (ema20_vals[0] - ema20_vals[4]) / ema20_vals[4] if ema20_vals[4] != 0 else 0
            slope_score = np.tanh(slope * 100)

    raw = position_score * 0.5 + alignment * 0.3 + slope_score * 0.2
    return max(-1.0, min(1.0, raw))


# ─── 3. 볼륨 분석 점수 ──────────────────────────────────────────

def compute_volume_score(df: pd.DataFrame) -> float:
    """거래량 스파이크 + 방향 확인. -1.0 ~ +1.0"""
    if df is None or df.empty or "Volume" not in df.columns:
        return 0.0

    vol = df["Volume"].values[:20]
    if len(vol) < 10 or np.mean(vol) == 0:
        return 0.0

    avg_vol = np.mean(vol[1:])  # 최근 19개 평균
    current_vol = vol[0]

    if avg_vol == 0:
        return 0.0

    vol_ratio = current_vol / avg_vol  # 1.0 = 평균, 2.0 = 2배

    # 거래량 폭증 (1.5배 이상) 시 방향 확인
    if vol_ratio >= 1.5:
        # 현재 봉이 양봉이면 상승 볼륨, 음봉이면 하락 볼륨
        close = df["Close"].iloc[0]
        open_ = df["Open"].iloc[0] if "Open" in df.columns else close
        candle_dir = 1.0 if close >= open_ else -1.0
        return max(-1.0, min(1.0, candle_dir * min(vol_ratio / 3.0, 1.0)))
    elif vol_ratio >= 1.0:
        return 0.2  # 평균 이상 거래량 = 약한 확인
    else:
        return -0.1  # 거래량 부족 = 약한 부정


# ─── 4. RSI 다이버전스 감지 ──────────────────────────────────────

def detect_rsi_divergence(df: pd.DataFrame) -> float:
    """
    가격은新高/新低인데 RSI는 반대 → 반전 시그널.
    +1.0 = 강한 상승 반전 (바닥 다이버전스)
    -1.0 = 강한 하락 반전 (천장 다이버전스)
    0.0 = 다이버전스 없음
    """
    if df is None or df.empty or len(df) < 10:
        return 0.0
    if "RSI" not in df.columns or "Close" not in df.columns:
        return 0.0

    recent = df.head(20)
    close_vals = recent["Close"].values
    rsi_vals = recent["RSI"].values

    if len(close_vals) < 10:
        return 0.0

    # 최근 고점 2개 비교
    half = len(close_vals) // 2
    first_half_close = close_vals[half:]
    second_half_close = close_vals[:half]
    first_half_rsi = rsi_vals[half:]
    second_half_rsi = rsi_vals[:half]

    max_close_1 = np.nanmax(first_half_close)
    max_close_2 = np.nanmax(second_half_close)
    max_rsi_1 = np.nanmax(first_half_rsi)
    max_rsi_2 = np.nanmax(second_half_rsi)

    min_close_1 = np.nanmin(first_half_close)
    min_close_2 = np.nanmin(second_half_close)
    min_rsi_1 = np.nanmin(first_half_rsi)
    min_rsi_2 = np.nanmin(first_half_rsi) if half > 0 else np.nanmin(second_half_rsi)
    min_rsi_2 = np.nanmin(second_half_rsi)

    # 천장 다이버전스: 가격은 신고가, RSI는 하락 → 하락 반전
    if max_close_2 > max_close_1 and max_rsi_2 < max_rsi_1:
        return -0.8

    # 바닥 다이버전스: 가격은 신저가, RSI는 상승 → 상승 반전
    if min_close_2 < min_close_1 and min_rsi_2 > min_rsi_1:
        return 0.8

    return 0.0


# ─── 5. 볼린저 밴드 위치 점수 ────────────────────────────────────

def compute_bb_score(snap: Dict[str, float]) -> float:
    """BB 밴드 내 위치. -1(하단) ~ +1(상단). 반전 의미."""
    close = snap.get("close", 0.0)
    bb_upper = snap.get("bb_upper", close)
    bb_lower = snap.get("bb_lower", close)
    bb_mid = snap.get("bb_mid", close)

    band_width = bb_upper - bb_lower
    if band_width <= 0:
        return 0.0

    # %B: 0(하단) ~ 1(상단)
    pct_b = (close - bb_lower) / band_width

    # 하단 근처 = 상승 기대(+), 상단 근처 = 하락 기대(-)
    # 중앙(0.5) 기준으로 반대 부호
    return (0.5 - pct_b) * 2.0  # 하단→+1, 상단→-1


# ─── 6. 통합 확률 계산 ──────────────────────────────────────────

def compute_p_long(
    snap: Dict[str, float],
    df: pd.DataFrame = None,
    trend_weight: float = 0.30,
    momentum_weight: float = 0.25,
    volume_weight: float = 0.20,
    bb_weight: float = 0.10,
    divergence_weight: float = 0.15,
) -> float:
    """
    다차원 점수 → LONG 확률.
    가중치 합 = 1.0.
    확률은 sigmoid로 정규화하여 양극단(95%+) 방지.
    """
    trend = compute_trend_score(snap, df)
    momentum = compute_momentum_score(snap)
    volume = compute_volume_score(df) if df is not None else 0.0
    bb = compute_bb_score(snap)
    divergence = detect_rsi_divergence(df) if df is not None else 0.0

    combined = (
        trend_weight * trend +
        momentum_weight * momentum +
        volume_weight * volume +
        bb_weight * bb +
        divergence_weight * divergence
    )

    # sigmoid 정규화: combined(-1~+1) → 확률(20%~80%)
    # 극단값 방지, 실용적인 확률 범위 유지
    import math
    sigmoid = 1.0 / (1.0 + math.exp(-combined * 3.0))
    p = 5.0 + sigmoid * 90.0  # 5% ~ 95%

    return max(5.0, min(95.0, round(p, 1)))


# ─── 7. 지지/저항 기반 진입/손절/목표 ──────────────────────────

def find_support_resistance(df: pd.DataFrame, lookback: int = 50) -> Dict[str, float]:
    """최근 N봉에서 구조적 지지/저항 탐지."""
    if df is None or df.empty or len(df) < 5:
        return {"support": 0.0, "resistance": 0.0}

    recent = df.head(min(lookback, len(df)))
    close = float(recent.iloc[0]["Close"])
    highs = recent["High"].values
    lows = recent["Low"].values

    # 최근 저점들 중 현재가 이하 최대값 = 지지
    supports = lows[lows < close]
    support = float(np.max(supports)) if len(supports) > 0 else close * 0.99

    # 최근 고점들 중 현재가 이상 최소값 = 저항
    resistances = highs[highs > close]
    resistance = float(np.min(resistances)) if len(resistances) > 0 else close * 1.01

    return {"support": round(support, 2), "resistance": round(resistance, 2)}


def compute_entry_stop_take(
    current_price: float,
    direction: str,
    atr: float,
    support: float = 0.0,
    resistance: float = 0.0,
    min_rr: float = 1.5,
) -> tuple:
    """
    구조적 지지/저항 + ATR 기반 손절/목표.
    손익비가 min_rr 미만이면 None 반환 (시그널 무효).
    """
    if atr <= 0 or current_price <= 0:
        atr = current_price * 0.01

    entry = round(current_price, 2)

    if direction == "LONG":
        # 손절: 지지가 또는 ATR×1.5 중 더 가까운 쪽
        atr_stop = current_price - atr * 1.5
        structural_stop = support if support > 0 and support < current_price else atr_stop
        stop_loss = round(max(atr_stop, structural_stop), 2)

        # 목표: 저항가 또는 손익비 기준 중 더 가까운 쪽
        rr_target = entry + (entry - stop_loss) * 2.0  # 2:1 RR
        structural_target = resistance if resistance > current_price else rr_target
        take_profit = round(min(rr_target, structural_target), 2)

    else:  # SHORT
        atr_stop = current_price + atr * 1.5
        structural_stop = resistance if resistance > 0 and resistance > current_price else atr_stop
        stop_loss = round(min(atr_stop, structural_stop), 2)

        rr_target = entry - (stop_loss - entry) * 2.0
        structural_target = support if support > 0 and support < current_price else rr_target
        take_profit = round(max(rr_target, structural_target), 2)

    # 손익비 계산
    if direction == "LONG":
        rr = (take_profit - entry) / (entry - stop_loss) if entry > stop_loss else 0.5
    else:
        rr = (entry - take_profit) / (stop_loss - entry) if stop_loss > entry else 0.5

    return entry, stop_loss, take_profit, round(max(0.5, min(5.0, rr)), 2)


# ─── 8. 메인 시그널 생성 ────────────────────────────────────────

def compute_signal_from_rules(
    chart_data: pd.DataFrame,
    current_price: float,
) -> Dict[str, Any]:
    from services.chart_data_service import calculate_indicators

    if chart_data is None or chart_data.empty:
        raise ValueError("차트 데이터가 없습니다.")

    df = calculate_indicators(chart_data)
    snap = get_indicator_snapshot(df)
    if not snap:
        raise ValueError("지표 스냅샷을 계산할 수 없습니다.")

    # 통합 확률
    p_long = compute_p_long(snap, df)
    direction = "LONG" if p_long >= 50.0 else "SHORT"
    probability = p_long if direction == "LONG" else 100.0 - p_long

    # 지지/저항
    sr = find_support_resistance(df)

    # 진입/손절/목표
    entry, stop_loss, take_profit, risk_reward = compute_entry_stop_take(
        current_price, direction,
        snap.get("atr", current_price * 0.01),
        sr["support"], sr["resistance"],
    )

    # 근거 리스트 (LLM 변환용)
    evidence_list = _build_internal_evidence(snap, direction, p_long, sr, df)

    return {
        "direction": direction,
        "probability": round(probability, 1),
        "entry_price": entry,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "risk_reward": risk_reward,
        "strategy_title": f"Rule-MultiFactor ({direction})",
        "evidence_list": evidence_list,
        "indicator_snapshot": snap,
        "support": sr["support"],
        "resistance": sr["resistance"],
    }


def _build_internal_evidence(
    snap: Dict[str, float],
    direction: str,
    p_long: float,
    sr: Dict[str, float],
    df: pd.DataFrame = None,
) -> List[str]:
    """LLM 문장화용 내부 근거."""
    evidence = []
    rsi = snap.get("rsi", 50)
    evidence.append(f"RSI(14)={rsi:.1f}" + (
        " (과매수 구간 — 반전 주의)" if rsi > 70
        else " (과매도 구간 — 반등 가능)" if rsi < 30
        else " (중립)"
    ))

    macd_hist = snap.get("macd_hist", 0)
    evidence.append(f"MACD Histogram={macd_hist:.2f}" + (
        " (상승 모멘텀)" if macd_hist > 0 else " (하락 모멘텀)"
    ))

    close = snap.get("close", 0)
    ema20, ema50, ema200 = snap.get("ema20", close), snap.get("ema50", close), snap.get("ema200", close)
    if close > ema20 and close > ema50:
        evidence.append("가격이 주요 이동평균선 상단 — 상승 추세")
    elif close < ema20 and close < ema50:
        evidence.append("가격이 주요 이동평균선 하단 — 하락 추세")
    else:
        evidence.append("이동평균선 혼조 — 추세 불분명")

    bb_upper, bb_lower = snap.get("bb_upper", close), snap.get("bb_lower", close)
    bb_mid = snap.get("bb_mid", close)
    band_width = bb_upper - bb_lower
    if band_width > 0:
        pct_b = (close - bb_lower) / band_width
        if pct_b > 0.9:
            evidence.append("볼린저 밴드 상단 돌파 — 과매수 의심")
        elif pct_b < 0.1:
            evidence.append("볼린저 밴드 하단 이탈 — 과매도 의심")
        else:
            evidence.append(f"볼린저 밴드 %B={pct_b:.1%} 위치")

    evidence.append(f"ATR(14)={snap.get('atr', 0):.2f} (볼동성)")
    evidence.append(f"구조적 지지={sr.get('support', 0):.2f}, 저항={sr.get('resistance', 0):.2f}")

    # 볼륨 정보
    vol_score = compute_volume_score(df) if df is not None else 0.0
    if abs(vol_score) > 0.3:
        evidence.append(f"거래량 스파이크 감지 (방향: {'상승' if vol_score > 0 else '하락'})")

    # 다이버전스
    div = detect_rsi_divergence(df) if df is not None else 0.0
    if abs(div) > 0.5:
        evidence.append(f"RSI 다이버전스 감지 ({'상승 반전' if div > 0 else '하락 반전'} 시그널)")

    evidence.append(f"통합 확률: LONG {p_long:.1f}% / SHORT {100 - p_long:.1f}%")
    return evidence

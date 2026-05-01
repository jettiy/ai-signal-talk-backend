"""
시그널 규칙 엔진: 방향/확률/진입·손절·목표 = 규칙 기반 수학적 계산.
모멘텀/추세/ATR 점수로 p_long 산출.
"""
from typing import Dict, List, Any
import pandas as pd
import numpy as np


def _safe(val: Any, default: float = 0.0) -> float:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


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
    }


def compute_momentum_score(snap: Dict[str, float]) -> float:
    rsi = snap.get("rsi", 50.0)
    macd_hist = snap.get("macd_hist", 0.0)
    rsi_score = (rsi - 50.0) / 50.0
    macd_sign = np.sign(macd_hist) if macd_hist != 0 else 0
    raw = 0.6 * rsi_score + 0.4 * float(macd_sign)
    return max(-1.0, min(1.0, raw))


def compute_trend_score(snap: Dict[str, float]) -> float:
    close = snap.get("close", 0.0)
    ema20 = snap.get("ema20", close)
    ema50 = snap.get("ema50", close)
    ema200 = snap.get("ema200", close)
    if close <= 0:
        return 0.0
    above_20 = 1.0 if close > ema20 else -1.0
    above_50 = 1.0 if close > ema50 else -1.0
    above_200 = 1.0 if close > ema200 else -1.0
    raw = (above_20 + above_50 + above_200) / 3.0
    return max(-1.0, min(1.0, raw))


def compute_p_long(snap: Dict[str, float], trend_weight: float = 0.5, momentum_weight: float = 0.5) -> float:
    trend = compute_trend_score(snap)
    momentum = compute_momentum_score(snap)
    combined = trend_weight * trend + momentum_weight * momentum
    p = 50.0 + 50.0 * combined
    return max(0.0, min(100.0, round(p, 1)))


def compute_entry_stop_take(
    current_price: float,
    direction: str,
    atr: float,
    atr_stop_mult: float = 1.5,
    atr_take_mult: float = 2.0,
    min_pct_stop: float = 0.005,
    min_pct_take: float = 0.01,
) -> tuple:
    if atr <= 0 or current_price <= 0:
        atr = current_price * 0.01
    stop_dist = max(atr * atr_stop_mult, current_price * min_pct_stop)
    take_dist = max(atr * atr_take_mult, current_price * min_pct_take)
    if direction == "LONG":
        entry = current_price
        stop_loss = entry - stop_dist
        take_profit = entry + take_dist
    else:
        entry = current_price
        stop_loss = entry + stop_dist
        take_profit = entry - take_dist
    return round(entry, 2), round(stop_loss, 2), round(take_profit, 2)


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

    p_long = compute_p_long(snap)
    direction = "LONG" if p_long >= 50.0 else "SHORT"
    probability = p_long if direction == "LONG" else 100.0 - p_long
    entry, stop_loss, take_profit = compute_entry_stop_take(
        current_price,
        direction,
        snap.get("atr", current_price * 0.01),
    )

    if direction == "LONG":
        rr = (take_profit - entry) / (entry - stop_loss) if entry > stop_loss else 1.0
    else:
        rr = (entry - take_profit) / (stop_loss - entry) if stop_loss > entry else 1.0
    risk_reward = round(max(0.5, min(5.0, rr)), 2)

    # LLM 문장화용 근거 (수치는 포함하되 사용자에게는 LLM이 자연어로 변환)
    evidence_list = _build_internal_evidence(snap, direction, p_long)

    return {
        "direction": direction,
        "probability": round(probability, 1),
        "entry_price": entry,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "risk_reward": risk_reward,
        "strategy_title": f"Rule-MomentumTrend ({direction})",
        "evidence_list": evidence_list,
        "indicator_snapshot": snap,
    }


def _build_internal_evidence(snap: Dict[str, float], direction: str, p_long: float) -> List[str]:
    """LLM 문장화용 내부 근거. 사용자에게 직접 노출하지 않음."""
    evidence = []
    rsi = snap.get("rsi", 50)
    evidence.append(f"RSI(14)={rsi:.1f}" + (" (과매수 구간)" if rsi > 70 else " (과매도 구간)" if rsi < 30 else " (중립)"))
    evidence.append(f"MACD Histogram={snap.get('macd_hist', 0):.2f}" + (" (상승 모멘텀)" if snap.get("macd_hist", 0) > 0 else " (하락 모멘텀)"))
    close = snap.get("close", 0)
    ema20, ema50 = snap.get("ema20", close), snap.get("ema50", close)
    if close > ema20 and close > ema50:
        evidence.append("가격이 이동평균선 상단에 위치하여 상승 추세 구간")
    elif close < ema20 and close < ema50:
        evidence.append("가격이 이동평균선 하단에 위치하여 하락 추세 구간")
    else:
        evidence.append("가격이 이동평균선과 엇갈린 혼조 구간")
    bb_mid, bb_upper, bb_lower = snap.get("bb_mid", close), snap.get("bb_upper", close), snap.get("bb_lower", close)
    if close >= bb_upper:
        evidence.append("변동성 밴드 상단 돌파")
    elif close <= bb_lower:
        evidence.append("변동성 밴드 하단 이탈")
    else:
        evidence.append("변동성 밴드 중앙 부근")
    evidence.append(f"ATR(14)={snap.get('atr', 0):.2f} (변동성)")
    evidence.append(f"규칙 엔진 결과: {direction} 쏠림, 확률 {p_long:.1f}%")
    return evidence

"""
시그널 분석: 시그널(방향/확률/진입·손절·목표) = 규칙 엔진 수학적 계산.
이유(문장) = LLM이 자연어로 설명 (기술 지표명 노출 없이).
"""
import asyncio
import httpx
import os
from typing import Dict, Optional, List
from services.chart_data_service import fetch_chart_data
from services.signal_rule_engine import compute_signal_from_rules


def _load_api_config():
    api_key = os.getenv("ZAI_API_KEY", "")
    api_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    model = "glm-4.5-air"
    return api_key, api_url, model


SYMBOL_NAMES = {
    "NQ1!": "나스닥 선물", "NQUSD": "나스닥 선물",
    "HSI1!": "항셍 선물", "HSIUSD": "항셍 선물",
    "GOLD": "금 선물", "GCUSD": "금 선물",
    "CL1!": "원유 선물", "CLUSD": "원유 선물",
    "KS1!": "코스피 선물", "KSUSD": "코스피 선물",
}

TIMEFRAME_NAMES = {
    "1": "1분봉", "5": "5분봉", "15": "15분봉", "30": "30분봉",
    "60": "60분봉", "1H": "60분봉", "1D": "일봉", "1W": "주봉", "1M": "월봉",
    "1min": "1분봉", "5min": "5분봉", "15min": "15분봉", "30min": "30분봉", "60min": "60분봉",
}


async def _llm_explain_signal(
    direction: str,
    probability: float,
    risk_reward: float,
    symbol_kr: str,
    timeframe_kr: str,
    evidence_list: List[str],
) -> str:
    """
    규칙 엔진 결과를 LLM이 트레이더 친화적 자연어로 설명.
    기술 지표명(RSI, MACD, EMA 등)을 직접 노출하지 않고,
    시장 모멘텀, 추세, 뉴스 영향 등 직관적 언어로 변환.
    """
    api_key, api_url, model = _load_api_config()
    if not api_key:
        return _fallback_explanation(direction, probability, risk_reward, evidence_list)

    system = """당신은 전문 트레이딩 애널리스트입니다. 기술적 지표 분석 결과를 바탕으로 트레이더가 이해하기 쉬운 자연스러운 설명을 작성하세요.

중요 규칙:
- RSI, MACD, EMA, 볼린저밴드, ATR 등 기술 지표명을 직접 언급하지 마세요.
- 대신 "시장 모멘텀", "상승/하락 추세", "변동성", "시장 심리", "가격 흐름" 등 트레이더가 직관적으로 이해하는 용어를 사용하세요.
- 2~4문장으로 간결하게 작성하세요.
- 왜 이 방향인지, 확률은 어느 정도인지, 현재 시장 상황이 어떤지를 자연스럽게 설명하세요."""

    user = f"""{symbol_kr} {timeframe_kr} 분석 결과:

- 분석 방향: {direction} ({'매수' if direction == 'LONG' else '매도'})
- 확률: {probability:.1f}%
- 손익비: {risk_reward:.1f}:1

내부 분석 근거 (참고용, 사용자에게 노출 금지):
{chr(10).join('- ' + e for e in evidence_list)}

위 정보를 바탕으로 트레이더가 이해하기 쉬운 설명을 작성하세요. 기술 지표명 대신 "시장 모멘텀이 상승세", "하락 압력이 강함", "변동성이 확대되며" 등 자연스러운 표현을 사용하세요."""

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.5,
                    "max_tokens": 400,
                },
            )
            if response.status_code == 200:
                result = response.json()
                if "choices" in result and result["choices"]:
                    content = result["choices"][0]["message"].get("content", "").strip()
                    if content:
                        return content
            return _fallback_explanation(direction, probability, risk_reward, evidence_list)
    except Exception as e:
        print(f"[SIGNAL_ANALYSIS] LLM 에러: {e}")
        return _fallback_explanation(direction, probability, risk_reward, evidence_list)


def _fallback_explanation(direction: str, probability: float, risk_reward: float, evidence_list: List[str]) -> str:
    """LLM 호출 실패 시 기본 설명 (지표명 없이)"""
    dir_text = "매수" if direction == "LONG" else "매도"
    momentum = "상승" if direction == "LONG" else "하락"
    return (
        f"현재 시장 모멘텀이 {momentum} 방향으로 강하게 나타나며, "
        f"종합 분석 결과 {dir_text} 방향으로 {probability:.0f}%의 확률을 보입니다. "
        f"손익비는 {risk_reward:.1f}:1로, 리스크 대비 수익 기대값이 {'유리' if risk_reward >= 1.5 else '중립'}한 상태입니다."
    )


async def analyze_signal(
    symbol: str,
    timeframe: str,
) -> Dict:
    """
    시그널 = 규칙 엔진(수학적 계산)으로 결정.
    설명 = LLM이 트레이더 친화적 자연어로 변환.
    """
    symbol_kr = SYMBOL_NAMES.get(symbol, symbol)
    timeframe_kr = TIMEFRAME_NAMES.get(timeframe, timeframe)

    print(f"[SIGNAL_ANALYSIS] Fetching chart data for {symbol} ({timeframe})...")

    chart_data = None
    for attempt in range(1, 4):
        chart_data = await fetch_chart_data(symbol, timeframe)
        if chart_data is not None and not chart_data.empty:
            break
        if attempt < 3:
            wait = 2.0 * attempt
            print(f"[SIGNAL_ANALYSIS] Retry {attempt}/3 in {wait}s")
            await asyncio.sleep(wait)

    if chart_data is None or chart_data.empty:
        raise ValueError(f"차트 데이터를 가져올 수 없습니다: {symbol} ({timeframe})")

    current_price = float(chart_data.iloc[0]["Close"])

    # 규칙 엔진: 수학적 계산으로 방향/확률/가격 결정
    raw = compute_signal_from_rules(chart_data, current_price)

    # LLM: 근거를 트레이더 친화적 자연어로 설명 (지표명 노출 없이)
    rationale = await _llm_explain_signal(
        direction=raw["direction"],
        probability=raw["probability"],
        risk_reward=raw["risk_reward"],
        symbol_kr=symbol_kr,
        timeframe_kr=timeframe_kr,
        evidence_list=raw["evidence_list"],
    )

    out = {
        "direction": raw["direction"],
        "probability": raw["probability"],
        "entry_price": raw["entry_price"],
        "take_profit": raw["take_profit"],
        "stop_loss": raw["stop_loss"],
        "risk_reward": raw["risk_reward"],
        "rationale": rationale,
    }
    print(f"[SIGNAL_ANALYSIS] Rule signal: {out['direction']} ({out['probability']:.1f}%)")
    return out

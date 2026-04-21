from fastapi import FastAPI, APIRouter
from pydantic import BaseModel
from typing import List

app = FastAPI()
router = APIRouter()

class IndicatorData(BaseModel):
    rsi: float
    macd_hist: float
    close: float
    ema20: float
    ema50: float
    ema200: float
    atr: float

class SignalRequest(BaseModel):
    symbol: str
    indicators: IndicatorData

@router.post("/api/v2/signal/rules")
async def get_signal_rules(request: SignalRequest):
    ind = request.indicators
    
    # 모멘텀 점수 (-1 ~ 1)
    momentum = (ind.rsi - 50) / 50
    
    # 추세 점수 (-1 ~ 1)
    trend = 0
    if ind.close > ind.ema20: trend += 0.33
    if ind.close > ind.ema50: trend += 0.33
    if ind.close > ind.ema200: trend += 0.34
    trend = (trend - 0.5) * 2
    
    # 확률 (0 ~ 100)
    p_long = 50 + 50 * (0.5 * trend + 0.5 * momentum)
    p_long = max(0, min(100, p_long))
    
    direction = "LONG" if p_long >= 50 else "SHORT"
    probability = p_long if direction == "LONG" else (100 - p_long)
    
    # 손절/목표가
    stop_loss = ind.close - (ind.atr * 1.5) if direction == "LONG" else ind.close + (ind.atr * 1.5)
    take_profit = ind.close + (ind.atr * 2.0) if direction == "LONG" else ind.close - (ind.atr * 2.0)
    
    # 최소 변화폭 적용
    min_change = ind.close * 0.005
    if abs(ind.close - stop_loss) < min_change:
        stop_loss = ind.close - min_change if direction == "LONG" else ind.close + min_change
        
    min_profit = ind.close * 0.01
    if abs(ind.close - take_profit) < min_profit:
        take_profit = ind.close + min_profit if direction == "LONG" else ind.close - min_profit
        
    evidence = [
        f"RSI={ind.rsi:.1f} ({'과매수' if ind.rsi > 70 else '과매도' if ind.rsi < 30 else '중립'})",
        f"MACD Histogram={ind.macd_hist:.2f} ({'상승' if ind.macd_hist > 0 else '하락'})",
        f"가격이 EMA20·50 {'위' if ind.close > ind.ema20 and ind.close > ind.ema50 else '아래'} (추세)"
    ]
    
    return {
        "direction": direction,
        "probability": round(probability, 1),
        "entry": ind.close,
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "risk_reward": 1.5,
        "evidence": evidence
    }

app.include_router(router)

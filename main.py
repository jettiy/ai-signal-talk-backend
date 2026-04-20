"""
AI Signal Talk Backend v2.1 — 단일 파일 FastAPI 서버
- Auth: 로그인/회원가입 (JSON body)
- Z.AI GLM 시그널 분석 연동
- 대화/메시지 관리
- SignalHistory
"""
import math
import os
import json
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy import text, cast, func, Date as SADate
from database import engine, Base, get_db, SessionLocal
from models import User, Conversation, Message, SignalHistory, UserRole
from auth import (
    get_password_hash,
    create_access_token,
    verify_password,
    get_current_user,
    get_current_active_user,
)

# ─── FastAPI 앱 ───
app = FastAPI(
    title="AI Signal Talk Backend",
    description="트레이딩 커뮤니티 백엔드 API",
    version="2.1.0",
)

# ─── CORS ───
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://ai-signal-talk.vercel.app")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Z.AI 설정 ───
ZAI_API_KEY = os.environ.get("ZAI_API_KEY", "")
ZAI_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


# ─── Startup ───
@app.on_event("startup")
async def startup_event():
    try:
        Base.metadata.create_all(bind=engine)
        print("DB 테이블 확인 완료")
        
        db = SessionLocal()
        try:
            admin_email = os.environ.get("ADMIN_EMAIL", "admin@signaltalk.ai")
            admin = db.query(User).filter(User.email == admin_email).first()
            if not admin:
                admin_pw = os.environ.get("ADMIN_PASSWORD", "admin123!")
                admin_nick = os.environ.get("ADMIN_NICKNAME", "관리자")
                admin = User(
                    email=admin_email,
                    hashed_password=get_password_hash(admin_pw),
                    nickname=admin_nick,
                    role="ADMIN",
                    is_active=1,
                )
                db.add(admin)
                db.commit()
                print(f"초기 관리자 계정 생성: {admin_email}")
        finally:
            db.close()
    except Exception as e:
        print(f"Startup 경고: {e}")


# ─── Health ───
@app.get("/api/health")
async def health_check():
    db_ok = False
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        db_ok = True
    except Exception:
        pass
    return {
        "status": "ok" if db_ok else "degraded",
        "version": "2.1.0",
        "db": db_ok,
        "auth": True,
        "websocket": True,
    }


@app.get("/")
async def root():
    return {"message": "AI Signal Talk Backend API", "version": "2.1.0"}


# ═══════════════════════════════════════════
# Auth API (v2 — JSON body)
# ═══════════════════════════════════════════

@app.post("/api/v2/auth/login")
async def v2_login(request: Request, db: Session = Depends(get_db)):
    """로그인 — JSON { email, password }"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="잘못된 요청 형식")

    email = body.get("email", "").strip()
    password = body.get("password", "")
    if not email or not password:
        raise HTTPException(status_code=400, detail="이메일과 비밀번호를 입력하세요.")

    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )
    if user.is_active != 1:
        raise HTTPException(status_code=403, detail="비활성 사용자")

    access_token = create_access_token(data={"sub": str(user.id)})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "nickname": user.nickname or "",
            "role": user.user_role.value,
            "is_pro": user.user_role in (UserRole.PRO, UserRole.ADMIN),
        },
    }


@app.post("/api/v2/auth/register")
async def v2_register(request: Request, db: Session = Depends(get_db)):
    """회원가입 — JSON { email, password, nickname }"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="잘못된 요청 형식")

    email = body.get("email", "").strip()
    password = body.get("password", "")
    nickname = body.get("nickname", "").strip()

    if not email or not password or not nickname:
        raise HTTPException(status_code=400, detail="모든 필드를 입력해주세요.")
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        raise HTTPException(status_code=400, detail="올바른 이메일 형식을 입력해주세요.")
    if len(password) < 8 or not re.search(r"[a-zA-Z]", password) or not re.search(r"[0-9]", password):
        raise HTTPException(status_code=400, detail="비밀번호는 영문+숫자 8자 이상이어야 합니다.")

    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다.")

    new_user = User(
        email=email,
        hashed_password=get_password_hash(password),
        nickname=nickname,
        role="BASIC",
        is_active=1,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    access_token = create_access_token(data={"sub": str(new_user.id)})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "nickname": new_user.nickname,
            "role": new_user.user_role.value,
            "is_pro": False,
        },
        "message": "회원가입이 완료되었습니다.",
    }


# ═══════════════════════════════════════════
# 사용자 정보
# ═══════════════════════════════════════════

@app.get("/api/v2/me")
async def get_me(current_user: User = Depends(get_current_active_user)):
    """내 정보 조회"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "nickname": current_user.nickname or "",
        "role": current_user.user_role.value,
        "is_pro": current_user.user_role in (UserRole.PRO, UserRole.ADMIN),
        "is_active": current_user.is_active == 1,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


# ═══════════════════════════════════════════
# 대화 & 메시지
# ═══════════════════════════════════════════

@app.get("/api/v2/conversations")
async def get_conversations(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    convs = db.query(Conversation).filter(
        Conversation.user_id == current_user.id
    ).order_by(Conversation.updated_at.desc()).all()
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in convs
        ]
    }


@app.post("/api/v2/conversations")
async def create_conversation(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    try:
        body = await request.json()
        title = body.get("title", "새로운 대화")
    except Exception:
        title = "새로운 대화"

    conv = Conversation(user_id=current_user.id, title=title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return {"conversation": {"id": conv.id, "title": conv.title, "created_at": conv.created_at.isoformat()}}


@app.get("/api/v2/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")

    msgs = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at.asc()).all()
    return {
        "messages": [
            {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
            for m in msgs
        ]
    }


@app.post("/api/v2/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """메시지 전송 + Z.AI 응답"""
    body = await request.json()
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="메시지를 입력하세요.")

    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")

    # 사용자 메시지 저장
    user_msg = Message(conversation_id=conversation_id, user_id=current_user.id, role="user", content=content)
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Z.AI 응답 생성
    ai_response = await _call_zai_chat(content)

    # AI 메시지 저장
    ai_msg = Message(conversation_id=conversation_id, user_id=current_user.id, role="assistant", content=ai_response)
    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)

    return {
        "user_message": {"id": user_msg.id, "role": "user", "content": content},
        "ai_message": {"id": ai_msg.id, "role": "assistant", "content": ai_response},
    }


# ═══════════════════════════════════════════
# Z.AI GLM 채팅
# ═══════════════════════════════════════════

async def _call_zai_chat(user_message: str, system_prompt: str = None) -> str:
    """Z.AI GLM-4.5-air 호출 (채팅)"""
    if not ZAI_API_KEY:
        return "AI 서비스가 현재 비활성화 상태입니다. 잠시 후 다시 시도해주세요."

    sys_msg = system_prompt or (
        "당신은 AI 시그널톡의 트레이딩 어시스턴트입니다. "
        "한국어로 친절하고 전문적으로 답변하세요. "
        "주식, 선물, 원자재 시장에 대한 분석과 시그널을 제공합니다."
    )

    payload = {
        "model": "glm-4.5-air",
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.7,
        "max_tokens": 1024,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{ZAI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {ZAI_API_KEY}"},
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                return msg.get("content") or msg.get("reasoning_content") or "응답을 생성할 수 없습니다."
            else:
                print(f"Z.AI 에러: {resp.status_code} {resp.text[:200]}")
                return f"AI 응답 생성에 실패했습니다. (status: {resp.status_code})"
    except httpx.TimeoutException:
        return "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."
    except Exception as e:
        print(f"Z.AI 호출 에러: {e}")
        return "AI 서비스 연결에 실패했습니다."


# ═══════════════════════════════════════════
# AI 시그널 분석
# ═══════════════════════════════════════════

SYMBOL_MAP = {
    "NQUSD": "나스닥 100 선물",
    "GCUSD": "금 선물",
    "CLUSD": "WTI 원유 선물",
}

@app.post("/api/v2/ai-signal")
async def generate_signal(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Z.AI GLM-5 시그널 분석"""
    body = await request.json()
    symbol = body.get("symbol", "NQUSD")
    timeframe = body.get("timeframe", "60min")

    symbol_kr = SYMBOL_MAP.get(symbol, symbol)

    # 예측 타입 결정
    if timeframe in ("1min", "5min"):
        prediction_type = "다음 봉 예측"
    else:
        prediction_type = "현재봉 마감 예측"

    prompt = f"""{symbol_kr} {timeframe} 타임프레임 기술적 분석을 수행하세요.

예측 타입: {prediction_type}
현재 시각: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

다음 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "signal_type": "LONG" 또는 "SHORT",
  "confidence": 1-100,
  "entry_price": 숫자,
  "target_price": 숫자,
  "stop_loss": 숫자,
  "risk_reward_ratio": 숫자,
  "buy_probability": 1-100,
  "sell_probability": 1-100,
  "rationale": "분석 근거 (한국어 2-3문장)",
  "prediction_type": "{prediction_type}"
}}"""

    payload = {
        "model": "glm-5",
        "messages": [
            {"role": "system", "content": "You are a professional trading analyst. Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 800,
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{ZAI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {ZAI_API_KEY}"},
                json=payload,
            )
            if resp.status_code == 200:
                data = resp.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or "{}"
            else:
                content = "{}"
    except Exception:
        content = "{}"

    # JSON 파싱 (코드블록 제거)
    try:
        cleaned = re.sub(r"```json\s*|\s*```", "", content).strip()
        signal_data = json.loads(cleaned)
    except json.JSONDecodeError:
        signal_data = {
            "signal_type": "LONG",
            "confidence": 50,
            "entry_price": 0,
            "target_price": 0,
            "stop_loss": 0,
            "risk_reward_ratio": 1.0,
            "buy_probability": 50,
            "sell_probability": 50,
            "rationale": "분석 데이터를 불러오지 못했습니다.",
            "prediction_type": prediction_type,
        }

    # SignalHistory 저장
    history = SignalHistory(
        user_id=current_user.id,
        symbol=symbol,
        timeframe=timeframe,
        signal_type=signal_data.get("signal_type", "LONG"),
        confidence=signal_data.get("confidence", 50),
        entry_price=signal_data.get("entry_price", 0),
        target_price=signal_data.get("target_price", 0),
        stop_loss=signal_data.get("stop_loss", 0),
        content=json.dumps(signal_data, ensure_ascii=False),
    )
    db.add(history)
    db.commit()

    return {**signal_data, "symbol": symbol, "timeframe": timeframe, "model": "glm-5"}


@app.get("/api/v2/signals/history")
async def get_signal_history(
    symbol: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """시그널 히스토리 조회"""
    q = db.query(SignalHistory).filter(SignalHistory.user_id == current_user.id)
    if symbol:
        q = q.filter(SignalHistory.symbol == symbol)
    histories = q.order_by(SignalHistory.created_at.desc()).limit(50).all()
    return {
        "history": [
            {
                "id": h.id,
                "symbol": h.symbol,
                "timeframe": h.timeframe,
                "signal_type": h.signal_type,
                "confidence": h.confidence,
                "entry_price": h.entry_price,
                "target_price": h.target_price,
                "stop_loss": h.stop_loss,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in histories
        ]
    }


# ═══════════════════════════════════════════
# Admin API (ADMIN 권한 필수)
# ═══════════════════════════════════════════

async def require_admin(current_user: User = Depends(get_current_active_user)) -> User:
    """ADMIN 권한 체크 dependency"""
    if current_user.user_role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다.")
    return current_user


@app.get("/api/v2/admin/users")
async def admin_list_users(
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """사용자 목록 조회 (ADMIN 전용)"""
    page = max(1, page)
    limit = max(1, min(limit, 100))

    q = db.query(User)
    if search:
        keyword = f"%{search}%"
        q = q.filter(User.email.ilike(keyword) | User.nickname.ilike(keyword))

    total = q.count()
    users = q.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "nickname": u.nickname or "",
                "role": u.user_role.value,
                "is_active": u.is_active == 1,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "totalPages": math.ceil(total / limit),
    }


@app.get("/api/v2/admin/stats")
async def admin_stats(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """플랫폼 통계 조회 (ADMIN 전용)"""
    from sqlalchemy import func as sa_func

    total_users = db.query(sa_func.count(User.id)).scalar()
    pro_users = db.query(sa_func.count(User.id)).filter(User.role == "PRO").scalar()
    basic_users = db.query(sa_func.count(User.id)).filter(User.role == "BASIC").scalar()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_signups = db.query(sa_func.count(User.id)).filter(User.created_at >= today_start).scalar()

    month_start = today_start - timedelta(days=30)
    monthly_active = db.query(sa_func.count(sa_func.distinct(Message.user_id))).filter(
        Message.created_at >= month_start
    ).scalar()

    return {
        "total_users": total_users,
        "pro_users": pro_users,
        "basic_users": basic_users,
        "today_signups": today_signups,
        "monthly_active": monthly_active,
    }


# ═══════════════════════════════════════════
# WebSocket 채팅
# ═══════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

    def disconnect(self, user_id: int):
        self.active_connections.pop(user_id, None)

    async def send_message(self, user_id: int, message: str):
        ws = self.active_connections.get(user_id)
        if ws:
            await ws.send_text(message)


manager = ConnectionManager()


@app.websocket("/ws/chat/{token}")
async def websocket_chat(websocket: WebSocket, token: str):
    payload = None
    try:
        from auth import decode_access_token
        payload = decode_access_token(token)
    except Exception:
        await websocket.close(code=4001)
        return

    if not payload:
        await websocket.close(code=4001)
        return

    user_id = int(payload.get("sub", 0))
    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Z.AI 응답
            ai_response = await _call_zai_chat(data)
            await manager.send_message(user_id, json.dumps({
                "type": "ai_response",
                "content": ai_response,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
    except WebSocketDisconnect:
        manager.disconnect(user_id)


@app.get("/api/v2/admin/consultations")
async def admin_consultations(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """관리자 상담 목록 (ADMIN 전용)"""
    from sqlalchemy.orm import joinedload
    import sqlalchemy.orm as orm

    convs = (
        db.query(Conversation)
        .options(orm.joinedload(Conversation.user))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
        .all()
    )

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    pending_count = db.query(Conversation).filter(Conversation.created_at >= cutoff).count()

    items = []
    for c in convs:
        msg_count = db.query(Message).filter(Message.conversation_id == c.id).count()
        last_msg_obj = (
            db.query(Message)
            .filter(Message.conversation_id == c.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        items.append({
            "id": c.id,
            "user_id": c.user_id,
            "nickname": c.user.nickname if c.user else "알 수 없음",
            "email": c.user.email if c.user else "",
            "title": c.title or "",
            "last_message": last_msg_obj.content[:80] if last_msg_obj else "",
            "message_count": msg_count,
            "status": "active",
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })

    return {"consultations": items, "pending_count": pending_count}


@app.get("/api/v2/admin/daily-signups")
async def admin_daily_signups(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """최근 30일 일일 가입자 수 (ADMIN 전용)"""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (
        db.query(
            cast(User.created_at, SADate).label('date'),
            func.count(User.id).label('count'),
        )
        .filter(User.created_at >= thirty_days_ago)
        .group_by(cast(User.created_at, SADate))
        .order_by(cast(User.created_at, SADate))
        .all()
    )
    return {
        "daily": [
            {"date": str(r.date), "count": r.count} for r in rows
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

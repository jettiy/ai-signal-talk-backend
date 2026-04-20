from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from database import engine, Base, get_db
from models import User, Conversation, Message, UserRole
from auth import (
    get_password_hash,
    create_access_token,
    verify_password,
    get_current_user,
    get_current_active_user
)
from websocket import manager, handle_websocket
import json

# DB 테이블 생성
Base.metadata.create_all(bind=engine)

# FastAPI 앱 생성
app = FastAPI(
    title="AI Signal Talk Backend",
    description="트레이딩 커뮤니티 백엔드 API",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 중에는 모든 origins 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """시작 시 초기화"""
    # 초기 관리자 계정 생성
    db = next(get_db())
    try:
        admin = db.query(User).filter(User.email == "admin@ai-signal-talk.com").first()
        if not admin:
            admin = User(
                email="admin@ai-signal-talk.com",
                hashed_password=get_password_hash("admin123"),
                role=UserRole.ADMIN,
                is_active=1
            )
            db.add(admin)
            db.commit()
            print("✅ 초기 관리자 계정 생성: admin@ai-signal-talk.com / admin123")
    finally:
        db.close()


@app.get("/")
async def root():
    """홈"""
    return {
        "message": "AI Signal Talk Backend API",
        "version": "1.0.0"
    }


# ===== 로그인 API =====
@app.post("/api/auth/login")
async def login(email: str, password: str, db: Session = Depends(get_db)):
    """로그인"""
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다."
        )

    if user.is_active != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성 사용자"
        )

    access_token = create_access_token(data={"sub": str(user.id)})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "role": user.role.value
        }
    }


# ===== 사용자 관리 API =====
@app.post("/api/users/register")
async def register(
    email: str,
    password: str,
    full_name: str,
    db: Session = Depends(get_db)
):
    """사용자 등록 (관리자 승인 필요)"""
    # 중복 이메일 확인
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 등록된 이메일입니다."
        )

    # 사용자 생성 (PENDING 상태)
    new_user = User(
        email=email,
        hashed_password=get_password_hash(password),
        full_name=full_name,
        role=UserRole.PENDING,
        is_active=1
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "가입이 완료되었습니다. 관리자 승인 후 사용 가능합니다.",
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "role": new_user.role.value
        }
    }


# ===== WebSocket API =====
@app.websocket("/ws/chat/{token}")
async def websocket_chat(
    websocket: WebSocket,
    token: str,
    db: Session = Depends(get_db)
):
    """WebSocket 채팅"""
    await handle_websocket(websocket, db, token)


# ===== 대화 관리 API =====
@app.get("/api/conversations")
async def get_conversations(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """사용자의 대화 목록 가져오기"""
    conversations = db.query(Conversation).filter(
        Conversation.user_id == current_user.id
    ).order_by(Conversation.updated_at.desc()).all()

    return {
        "conversations": [
            {
                "id": conv.id,
                "title": conv.title,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat()
            }
            for conv in conversations
        ]
    }


@app.post("/api/conversations")
async def create_conversation(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """새 대화 생성"""
    new_conversation = Conversation(
        user_id=current_user.id,
        title="새로운 대화"
    )
    db.add(new_conversation)
    db.commit()
    db.refresh(new_conversation)

    return {
        "conversation": {
            "id": new_conversation.id,
            "title": new_conversation.title,
            "created_at": new_conversation.created_at.isoformat()
        }
    }


# ===== 메시지 관리 API =====
@app.get("/api/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """대화의 메시지 목록 가져오기"""
    # 대화 확인
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id
    ).first()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="대화를 찾을 수 없습니다."
        )

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at.asc()).all()

    return {
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

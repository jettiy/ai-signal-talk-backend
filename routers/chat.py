"""채팅 라우터"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
import models, database, uuid, datetime

router = APIRouter()


class ChatMessageIn(BaseModel):
    content: str
    nickname: Optional[str] = None
    grade: Optional[str] = None


class ChatMessageOut(BaseModel):
    id: str; nickname: str; grade: str; content: str; is_bot: bool; created_at: datetime.datetime


@router.get("/", response_model=list[ChatMessageOut])
async def get_messages(limit: int = 50, db: Session = Depends(database.get_db)):
    msgs = db.query(models.ChatMessage).order_by(
        models.ChatMessage.created_at.desc()
    ).limit(limit).all()
    return list(reversed(msgs))


@router.post("/", response_model=ChatMessageOut)
async def send_message(body: ChatMessageIn, db: Session = Depends(database.get_db)):
    msg = models.ChatMessage(
        id=str(uuid.uuid4()),
        user_id="anonymous",
        nickname=body.nickname or "손님",
        grade=body.grade or "LV.01",
        content=body.content,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg

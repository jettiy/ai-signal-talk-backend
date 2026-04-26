"""
인증 라우터 — 회원가입 / 로그인 / JWT
"""
import os
import re
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session
import uuid

from database import get_db
import models

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-fallback-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7일


# --- Pydantic Schema ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    nickname: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("비밀번호는 8자 이상이어야 합니다.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("영문자를 포함해야 합니다.")
        if not re.search(r"\d", v):
            raise ValueError("숫자를 포함해야 합니다.")
        return v

    @field_validator("nickname")
    @classmethod
    def sanitize_nickname(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2 or len(v) > 20:
            raise ValueError("닉네임은 2~20자 사이여야 합니다.")
        # [XSS FIX] HTML 특수문자 이스케이프
        from html import escape
        return escape(v)


class UserResponse(BaseModel):
    id: str
    email: str
    nickname: str
    level: str
    is_pro: bool
    created_at: str | None = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProAppCreate(BaseModel):
    requested_role: str
    reason: str


class ProAppOut(BaseModel):
    id: int
    user_id: str
    user_email: str
    requested_role: str
    status: str

    class Config:
        from_attributes = True


# --- JWT 유틸 ---
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if user.level != "LEVEL_99":
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return user


# --- API 엔드포인트 ---

@router.post("/register", response_model=UserResponse)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다.")

    user = models.User(
        id=str(uuid.uuid4()),
        email=user_in.email,
        hashed_password=pwd_context.hash(user_in.password),
        nickname=user_in.nickname,
        level="LEVEL_01",
        is_pro=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    access_token = create_access_token(data={"sub": user.id, "email": user.email})
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: models.User = Depends(get_current_user)):
    return current_user

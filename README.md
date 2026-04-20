# AI Signal Talk Backend

FastAPI + PostgreSQL + WebSocket 채팅 서버

## Tech Stack

- **FastAPI** - 최신 Python 웹 프레임워크
- **SQLAlchemy** - ORM
- **PostgreSQL** - 데이터베이스 (개발 중에는 SQLite 사용 가능)
- **WebSocket** - 실시간 채팅
- **JWT** - 인증

## Installation

```bash
# 가상환경 생성 (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# 의존성 설치
pip install -r requirements.txt
```

## Setup

### 1. 데이터베이스 설정

```python
# database.py
DATABASE_URL = "postgresql://user:password@localhost:5432/ai_signal_talk"
```

또는 개발 중에는 SQLite 사용:

```python
DATABASE_URL = "sqlite:///./ai_signal_talk.db"
```

### 2. 초기 관리자 계정

시작 시 자동으로 생성됩니다:
- 이메일: `admin@ai-signal-talk.com`
- 비밀번호: `admin123`

### 3. 서버 실행

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

### 인증
- `POST /api/auth/login` - 로그인
- `POST /api/users/register` - 사용자 등록

### 대화 관리
- `GET /api/conversations` - 대화 목록
- `POST /api/conversations` - 새 대화 생성

### 메시지 관리
- `GET /api/conversations/{conversation_id}/messages` - 메시지 목록

### WebSocket
- `WS /ws/chat/{token}` - 실시간 채팅

## Usage

### 로그인

```bash
curl -X POST "http://localhost:8000/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@ai-signal-talk.com","password":"admin123"}'
```

### WebSocket 연결

```javascript
const token = "your_access_token";
const ws = new WebSocket(`ws://localhost:8000/ws/chat/${token}`);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);
};

ws.send(JSON.stringify({
  type: "message",
  conversation_id: 1,
  content: "Hello!"
}));
```

## RBAC (Role-Based Access Control)

- **BASIC**: 기본 사용자
- **PENDING**: 관리자 승인 대기 중
- **PRO**: 관리자 승인된 PRO 사용자
- **ADMIN**: 관리자

## Development

### Database Migration (선택 사항)

```bash
# Alembic 설치
pip install alembic

# 마이그레이션 생성
alembic revision --autogenerate -m "initial"

# 마이그레이션 실행
alembic upgrade head
```

## License

MIT

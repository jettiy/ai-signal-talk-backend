"""PRO 상담 신청 라우터"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
import models, database, uuid, datetime

router = APIRouter()

class ProAppIn(BaseModel):
    name: str; phone: str; email: EmailStr

class ProAppOut(BaseModel):
    id: str; name: str; phone: str; email: str; status: str; created_at: datetime.datetime

@router.post("/", response_model=ProAppOut)
async def submit(body: ProAppIn, db: Session = Depends(database.get_db)):
    if db.query(models.ProApplication).filter(models.ProApplication.email == body.email).first():
        raise HTTPException(status_code=400, detail="이미 신청된 이메일입니다.")
    app = models.ProApplication(id=str(uuid.uuid4()), name=body.name, phone=body.phone, email=body.email)
    db.add(app); db.commit(); db.refresh(app)
    return app

@router.get("/", response_model=list[ProAppOut])
async def list_apps(db: Session = Depends(database.get_db)):
    return db.query(models.ProApplication).order_by(models.ProApplication.created_at.desc()).all()

@router.patch("/{app_id}/status")
async def update_status(app_id: str, status: str, db: Session = Depends(database.get_db)):
    app = db.query(models.ProApplication).filter(models.ProApplication.id == app_id).first()
    if not app: raise HTTPException(404, "찾을 수 없습니다.")
    app.status = status; db.commit()
    return {"ok": True}

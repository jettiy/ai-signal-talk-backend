"""
초기 데이터베이스 설정 스크립트
채널 생성 등
"""
from database import SessionLocal, engine, Base
from models import Channel


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 기본 채널 6개 (코스피 추가)
        channels = [
            {"name": "Global", "symbol": None},
            {"name": "NASDAQ", "symbol": "NQUSD"},
            {"name": "HSI", "symbol": "HSIUSD"},
            {"name": "GOLD", "symbol": "GCUSD"},
            {"name": "OIL", "symbol": "CLUSD"},
            {"name": "KOSPI", "symbol": "KSUSD"},
        ]

        for ch_data in channels:
            existing = db.query(Channel).filter(Channel.name == ch_data["name"]).first()
            if not existing:
                channel = Channel(**ch_data)
                db.add(channel)

        db.commit()
        print("Database initialized successfully - 6 channels created")
    except Exception as e:
        print(f"Error initializing database: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    init_db()

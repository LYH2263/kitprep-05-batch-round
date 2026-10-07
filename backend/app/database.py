from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_columns() -> None:
    """create_all 只建新表不补列；老库缺 ingredients.prep_multiple 时就地补上。"""
    insp = inspect(engine)
    if insp.has_table("ingredients"):
        cols = {c["name"] for c in insp.get_columns("ingredients")}
        if "prep_multiple" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE ingredients ADD COLUMN prep_multiple DOUBLE PRECISION"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

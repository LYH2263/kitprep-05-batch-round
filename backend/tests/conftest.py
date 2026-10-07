import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SEED_ON_EMPTY", "false")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.models import (  # noqa: E402
    BomLine, Dish, Ingredient, KitchenOrder, OrderLine,
)


@pytest.fixture()
def ctx():
    """每测一套内存库 + 直接查询会话 + 走完整 HTTP 栈的 client。"""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    db = Session()
    d = Dish(code="D1", name="套餐", portion_unit="份")
    db.add(d); db.flush()
    meat = Ingredient(code="M", name="肉", unit="kg", stock_qty=4.0, prep_multiple=None)
    rice = Ingredient(code="R", name="米", unit="kg", stock_qty=50.0, prep_multiple=None)
    db.add_all([meat, rice]); db.flush()
    # 33 份 × 0.1 = 散数 3.3；米单耗 0 → 散数 0（取整后也必须留行、占量 0）
    db.add_all([
        BomLine(dish_id=d.id, ingredient_id=meat.id, qty_per_portion=0.1),
        BomLine(dish_id=d.id, ingredient_id=rice.id, qty_per_portion=0.0),
    ])
    o_open = KitchenOrder(code="KO-OPEN", outlet="城西", status="open")
    o_closed = KitchenOrder(code="KO-CLOSED", outlet="城东", status="closed")
    db.add_all([o_open, o_closed]); db.flush()
    db.add(OrderLine(order_id=o_open.id, dish_id=d.id, portions=33))
    db.add(OrderLine(order_id=o_closed.id, dish_id=d.id, portions=33))
    db.commit()
    ids = {"dish": d.id, "meat": meat.id, "rice": rice.id,
           "open": o_open.id, "closed": o_closed.id}

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    try:
        yield {"client": TestClient(app), "db": db, "ids": ids, "Session": Session}
    finally:
        app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(engine)

"""起备倍数的落单行为:保存倍数 → 在用单整张重写;旧单不动;非法倍数全回退。"""
import json
import os
import tempfile

_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from app.database import SessionLocal
from app.main import app
from app.models.models import Ingredient, PrepRun


@pytest.fixture(scope="module")
def app_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(app_client):
    """每个用例回到干净状态:没有已落单、所有原料未配倍数。"""
    db = SessionLocal()
    try:
        db.execute(delete(PrepRun))
        db.execute(update(Ingredient).values(prep_multiple=None))
        db.commit()
    finally:
        db.close()
    return app_client


def _line(sheet: dict, code: str) -> dict:
    return next(l for l in sheet["prep_lines"] if l["ingredient_code"] == code)


def _ing_id(client, code: str) -> int:
    return next(r["id"] for r in client.get("/api/inventory").json() if r["code"] == code)


def _run_count() -> int:
    db = SessionLocal()
    try:
        return len(db.scalars(select(PrepRun)).all())
    finally:
        db.close()


def _stored_sheet(run_id: int) -> dict:
    db = SessionLocal()
    try:
        return json.loads(db.get(PrepRun, run_id).result_json)
    finally:
        db.close()


def test_generate_without_multiple_no_rounding(client):
    sheet = client.post("/api/prep/run?order_id=1").json()
    sc = _line(sheet, "I-SC")
    assert sc["need_qty"] == 1.75
    assert sc["reserved_qty"] == 1.75  # 没配倍数:占用=需求,不取整
    assert sc["prep_multiple"] is None
    assert sc["shortage"] == 0.0


def test_save_multiple_rewrites_active_sheet_and_keeps_history(client):
    run1 = client.post("/api/prep/run?order_id=1").json()
    sc_id = _ing_id(client, "I-SC")

    res = client.put(f"/api/inventory/{sc_id}/multiple", json={"prep_multiple": 0.5})
    assert res.status_code == 200
    assert res.json()["rewritten_runs"] == [run1["id"]]

    latest = client.get("/api/prep/latest?order_id=1").json()
    assert latest["id"] == run1["id"]  # 同一张单原地重写,不是新落一张
    sc = _line(latest, "I-SC")
    assert sc["need_qty"] == 1.75
    assert sc["reserved_qty"] == 2.0   # 1.75 按 0.5 四舍五入
    assert sc["prep_multiple"] == 0.5
    assert sc["shortage"] == 0.0       # 占用 2.0 − 库存 2.0
    assert _line(latest, "I-RC")["reserved_qty"] == 10.5  # 没配倍数的不取整

    # 再落一张新单,然后改倍数:只有正在用的那张被重写
    run2 = client.post("/api/prep/run?order_id=1").json()
    assert run2["id"] != run1["id"]
    res = client.put(f"/api/inventory/{sc_id}/multiple", json={"prep_multiple": 3.0})
    assert res.json()["rewritten_runs"] == [run2["id"]]

    latest = client.get("/api/prep/latest?order_id=1").json()
    sc = _line(latest, "I-SC")
    assert sc["reserved_qty"] == 3.0
    assert sc["shortage"] == 1.0  # 占用 3.0 − 库存 2.0

    # 缺料贴与备料台、占用列同口径
    sticky = client.get("/api/prep/shortages?order_id=1").json()
    sc_sticky = next(s for s in sticky["shortages"] if s["ingredient_code"] == "I-SC")
    assert sc_sticky["reserved_qty"] == 3.0
    assert sc_sticky["shortage"] == 1.0

    # 已经落下的旧单:占用列禁止跟着改(仍停留在 0.5 倍口径)
    old_sc = _line(_stored_sheet(run1["id"]), "I-SC")
    assert old_sc["reserved_qty"] == 2.0
    assert old_sc["prep_multiple"] == 0.5


def test_invalid_multiple_rejected_everything_unchanged(client):
    client.post("/api/prep/run?order_id=1")
    before_sheet = client.get("/api/prep/latest?order_id=1").json()
    before_inv = client.get("/api/inventory").json()
    before_runs = _run_count()
    sc_id = _ing_id(client, "I-SC")

    for bad in (0, -2):
        res = client.put(f"/api/inventory/{sc_id}/multiple", json={"prep_multiple": bad})
        assert res.status_code == 400

    # 栏、单、缺料贴都停在写入前
    assert client.get("/api/inventory").json() == before_inv
    assert client.get("/api/prep/latest?order_id=1").json() == before_sheet
    assert _run_count() == before_runs


def test_round_to_zero_keeps_row(client):
    client.post("/api/prep/run?order_id=1")
    ol_id = _ing_id(client, "I-OL")  # 需求 1.95,倍数 5 → 0.39 批 → 取整为 0
    res = client.put(f"/api/inventory/{ol_id}/multiple", json={"prep_multiple": 5.0})
    assert res.status_code == 200

    latest = client.get("/api/prep/latest?order_id=1").json()
    ol = _line(latest, "I-OL")  # 必须留行,禁止当「没有这料」删行
    assert ol["need_qty"] == 1.95
    assert ol["reserved_qty"] == 0.0
    assert ol["shortage"] == 0.0
    assert all(s["ingredient_code"] != "I-OL" for s in latest["shortages"])


def test_stock_not_decreased_after_save(client):
    client.post("/api/prep/run?order_id=1")
    before = {r["code"]: r["stock_qty"] for r in client.get("/api/inventory").json()}
    pr_id = _ing_id(client, "I-PR")
    res = client.put(f"/api/inventory/{pr_id}/multiple", json={"prep_multiple": 15.0})
    assert res.status_code == 200
    # 需求 10 按 15 进成 1 批:占用 15、缺料 7,但库存结存禁止比保存前更少
    sc = _line(client.get("/api/prep/latest?order_id=1").json(), "I-PR")
    assert sc["reserved_qty"] == 15.0 and sc["shortage"] == 7.0
    after = {r["code"]: r["stock_qty"] for r in client.get("/api/inventory").json()}
    assert after == before


def test_same_caliber_between_save_and_regenerate(client):
    sc_id = _ing_id(client, "I-SC")
    client.post("/api/prep/run?order_id=1")
    client.put(f"/api/inventory/{sc_id}/multiple", json={"prep_multiple": 0.5})
    rewritten = client.get("/api/prep/latest?order_id=1").json()

    regenerated = client.post("/api/prep/run?order_id=1").json()
    # 原料页改倍数与备料台再生成:取整结果同一口径
    assert regenerated["prep_lines"] == rewritten["prep_lines"]
    assert regenerated["shortages"] == rewritten["shortages"]


def test_clear_multiple_restores_unrounded(client):
    sc_id = _ing_id(client, "I-SC")
    client.post("/api/prep/run?order_id=1")
    client.put(f"/api/inventory/{sc_id}/multiple", json={"prep_multiple": 0.5})
    res = client.put(f"/api/inventory/{sc_id}/multiple", json={"prep_multiple": None})
    assert res.status_code == 200
    sc = _line(client.get("/api/prep/latest?order_id=1").json(), "I-SC")
    assert sc["prep_multiple"] is None
    assert sc["reserved_qty"] == 1.75  # 没配过倍数则不取整

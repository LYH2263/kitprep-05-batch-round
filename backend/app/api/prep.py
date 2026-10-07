import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import KitchenOrder
from app.services import prep_service

router = APIRouter(prefix="/prep", tags=["prep"])


@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    """生成备料单：只出单。按当前倍数栏取整后落一张新单（快照）。"""
    order = db.get(KitchenOrder, order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    try:
        # 与原料页保存倍数同一把锁：撞在一起时，取整结果同一口径、互不覆盖。
        prep_service.lock_ingredients(db)
        run = prep_service.create_run(db, order_id)
        db.commit()
        db.refresh(run)
    except Exception:
        db.rollback()
        raise
    return {"id": run.id, **json.loads(run.result_json)}


@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    """读正在用的那张单：只读出已落快照，绝不打开再按栏位现算冒充已落单。"""
    run = prep_service.latest_run(db, order_id)
    if not run:
        # 还没落过单才现算落一张，保证返回的永远是一张真实存在的单。
        return run_prep(order_id=order_id, db=db)
    return {"id": run.id, **json.loads(run.result_json)}


@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    data = latest(order_id=order_id, db=db)
    return {"order_id": order_id, "shortages": data.get("shortages", []), "stats": data.get("stats", {})}

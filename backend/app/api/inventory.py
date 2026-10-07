import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Ingredient
from app.services import prep_service

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _serialize(r: Ingredient) -> dict:
    return {"id": r.id, "code": r.code, "name": r.name, "unit": r.unit,
            "stock_qty": r.stock_qty, "prep_multiple": r.prep_multiple}


@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    return [_serialize(r) for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()]


class MultipleIn(BaseModel):
    # null / 空串 = 清掉倍数（没配过，不取整）；其余必须是正数
    prep_multiple: float | str | None = None


@router.put("/{ingredient_id}/multiple")
def save_multiple(ingredient_id: int, body: MultipleIn, db: Session = Depends(get_db)):
    raw = body.prep_multiple
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        multiple: float | None = None
    else:
        if isinstance(raw, str):
            raise HTTPException(400, "倍数必须是正数；0、负数或非数字一律不写入")
        multiple = float(raw)
        if not math.isfinite(multiple) or multiple <= 0:
            # 栏、单、缺料贴全部停在写入前：此刻尚未改任何东西。
            raise HTTPException(400, "倍数必须是正数；0、负数一律不写入")

    try:
        # 与“生成备料单”同一把锁、同一 id 顺序：倍数保存与备料台再生成互斥，
        # 两个并发保存之间也串行，杜绝同一张单被后写覆盖。
        prep_service.lock_ingredients(db)

        ing = db.get(Ingredient, ingredient_id)
        if ing is None:
            raise HTTPException(404, "原料不存在")

        stock_before = ing.stock_qty  # 结存只允许原样带过，保存后禁止变少

        # 1) 栏先定
        ing.prep_multiple = multiple

        # 2) 正在用的那张单：每个 open 订单只取最新一张，整张按新倍数重写。
        #    历史单不取、不改；任一单写不进则随事务整体回滚，栏一起退回。
        rewritten = []
        for run in prep_service.latest_runs_for_ingredient(db, ingredient_id):
            prep_service.rewrite_run_with_multiple(run, ingredient_id, multiple)
            rewritten.append({"order_id": run.order_id, "run_id": run.id})

        # 红线：本流程只改栏与单，结存必须与保存前一致（禁止变少）。
        if ing.stock_qty != stock_before:
            raise HTTPException(409, "结存发生变化，已退回写入前")

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(500, "倍数与备料单未达成一致，已全部退回写入前")

    db.refresh(ing)
    return {**_serialize(ing), "rewritten_runs": rewritten}

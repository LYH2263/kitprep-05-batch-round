from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ingredient
from app.services.prep_sheet import rewrite_active_sheets
router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    return [{"id": r.id, "code": r.code, "name": r.name, "unit": r.unit,
             "stock_qty": r.stock_qty, "prep_multiple": r.prep_multiple}
            for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()]

class MultipleIn(BaseModel):
    # null = 清除倍数(没配过则不取整);>0 = 起备倍数
    prep_multiple: float | None = None

@router.put("/{ingredient_id}/multiple")
def set_multiple(ingredient_id: int, body: MultipleIn, db: Session = Depends(get_db)):
    """保存起备倍数:栏位与「正在用的那张单」同事务落库。

    - 倍数为 0 或负数:整体拒绝,栏、单、缺料贴全部停在写入前。
    - 成功:倍数写栏,同时每个订单最新一张单整张按新倍数取整重写
      (占用列 + 缺料贴);旧单不动;库存结存不变。
    """
    ing = db.get(Ingredient, ingredient_id)
    if not ing: raise HTTPException(404, "原料不存在")
    v = body.prep_multiple
    if v is not None and v <= 0:
        raise HTTPException(400, "起备倍数必须为正数;栏、单、缺料贴均保持写入前状态")
    ing.prep_multiple = v
    try:
        rewritten = rewrite_active_sheets(db)
        db.commit()
    except Exception:
        db.rollback()  # 整张停住,倍数栏一起退回
        raise
    return {"id": ing.id, "code": ing.code, "prep_multiple": ing.prep_multiple,
            "rewritten_runs": rewritten}

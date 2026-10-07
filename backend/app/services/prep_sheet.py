"""备料单的落单与重写:生成与倍数变更共用同一套取整口径。

- build_sheet_result:按当前原料配置(库存 + 起备倍数)整张算出备料单。
- rewrite_active_sheets:把每个订单「正在用的那张单」(最新一张 PrepRun)
  整张按当前配置重写占用列与缺料贴;已经落下的旧单一律不动。
"""
from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import explode_and_merge, result_to_dict


def build_sheet_result(db: Session, order: KitchenOrder) -> dict:
    """按当前配置整张算单:备料台再生成与倍数保存重写都走这里,口径一致。"""
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit,
                   "stock_qty": i.stock_qty, "prep_multiple": i.prep_multiple}
            for i in db.scalars(select(Ingredient)).all()}
    result = result_to_dict(explode_and_merge(ols, bom, ings))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return result


def rewrite_active_sheets(db: Session) -> list[int]:
    """整张重写每个订单最新一张 PrepRun(占用列 + 缺料贴),返回被重写的 run id。

    只更新每订单 id 最大的那张;历史旧单的 result_json 保持原样。
    调用方负责 commit/rollback —— 与倍数写栏位同事务,要么一起成,要么一起退。
    """
    latest_ids = db.scalars(select(func.max(PrepRun.id)).group_by(PrepRun.order_id)).all()
    rewritten: list[int] = []
    for run_id in latest_ids:
        run = db.get(PrepRun, run_id)
        order = db.get(KitchenOrder, run.order_id)
        if order is None:
            continue
        run.result_json = json.dumps(build_sheet_result(db, order), ensure_ascii=False)
        rewritten.append(run.id)
    return rewritten

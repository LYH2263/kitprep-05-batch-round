"""备料单落单的唯一口径：载入订单行 / BOM / 倍数栏 → explode → PrepRun 快照。

/prep/run（备料台生成）与原料页保存倍数都走这里，保证两处取整同一口径。
快照一旦落下就是一张单：占用列与缺料贴冻结，之后只允许被“整张按新倍数重写”，
不会被重新打开时现算冒充。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import apply_multiples, explode_and_merge, result_to_dict


def load_ingredient_map(db: Session) -> dict[int, dict]:
    return {
        i.id: {
            "code": i.code,
            "name": i.name,
            "unit": i.unit,
            "stock_qty": i.stock_qty,
            "prep_multiple": i.prep_multiple,
        }
        for i in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()
    }


def lock_ingredients(db: Session, ingredient_id: int | None = None) -> list[Ingredient]:
    """锁原料行以串行化“生成备料单”和“保存倍数”。统一按 id 顺序加锁，避免死锁。

    run 锁全部（占用列依赖所有原料的倍数）；保存只锁本行，但两边加锁顺序一致，
    不会出现环等。
    """
    stmt = select(Ingredient).order_by(Ingredient.id).with_for_update()
    if ingredient_id is not None:
        stmt = stmt.where(Ingredient.id == ingredient_id)
    return list(db.scalars(stmt).all())


def build_order_result(db: Session, order: KitchenOrder) -> dict:
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    result = result_to_dict(explode_and_merge(ols, bom, load_ingredient_map(db)))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return result


def create_run(db: Session, order_id: int) -> PrepRun:
    """落一张新单（调用方已持锁）。只在“生成备料单”时调用。"""
    order = db.get(KitchenOrder, order_id)
    if order is None:
        raise LookupError(order_id)
    result = build_order_result(db, order)
    run = PrepRun(order_id=order_id, created_at=datetime.utcnow(),
                  result_json=json.dumps(result, ensure_ascii=False))
    db.add(run)
    db.flush()
    return run


def latest_run(db: Session, order_id: int) -> PrepRun | None:
    return db.scalars(
        select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id.desc())
    ).first()


def latest_runs_for_ingredient(db: Session, ingredient_id: int) -> list[PrepRun]:
    """各 open 订单“正在用的那张单”（最新一张）中、含该原料行的单子。

    已经落下的旧单不在这里面——每个订单只取最新一张，历史单永不被倍数保存改写。
    """
    order_ids = list(db.scalars(
        select(KitchenOrder.id).where(KitchenOrder.status == "open")
    ).all())
    hits: list[PrepRun] = []
    for oid in order_ids:
        run = latest_run(db, oid)
        if run is None:
            continue
        data = json.loads(run.result_json)
        if any(l.get("ingredient_id") == ingredient_id for l in data.get("prep_lines", [])):
            hits.append(run)
    return hits


def rewrite_run_with_multiple(run: PrepRun, ingredient_id: int, multiple: float | None) -> dict:
    """把一张在用单整张按新倍数重写（占用列 + 缺料贴一次产出，行不增删）。"""
    data = json.loads(run.result_json)
    data = apply_multiples(data, {ingredient_id: {"prep_multiple": multiple}})
    run.result_json = json.dumps(data, ensure_ascii=False)
    return data

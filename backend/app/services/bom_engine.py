"""Central kitchen BOM explode: order lines × BOM qty, merge ingredients, round the
occupied quantity up by the ingredient prep multiple, shortage = occupied - stock.

倍数（prep_multiple）口径只有一个：备料台「生成备料单」与原料页保存倍数都走
round_up_multiple。倍数为空（None）表示没配过，不取整。
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    raw_need_qty: float          # BOM 散数需求（份数 × 单耗，永不取整）
    prep_multiple: float | None  # 起备倍数；None = 没配过，不取整
    need_qty: float              # 占用列：按倍数向上取整后的占用量
    stock_qty: float
    shortage: float


def _clean_multiple(value) -> float | None:
    """None/空串/NaN 视为没配过；正数才生效。"""
    if value is None:
        return None
    try:
        m = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(m) or math.isinf(m) or m <= 0:
        return None
    return m


def round_up_multiple(qty: float, multiple) -> float:
    """散数按起备倍数向上取整；没配倍数（None/非正）时原样返回。"""
    m = _clean_multiple(multiple)
    if m is None:
        return round(float(qty), 3)
    rounded = math.ceil(qty / m - 1e-9) * m
    return round(rounded, 3)


def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion.

    ingredients 可带 prep_multiple；占用列 = 散数需求按倍数向上取整，缺料贴同口径。
    """
    need: dict[int, float] = {}
    for ol in order_lines:
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            need[bl["ingredient_id"]] = need.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"]
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        multiple = _clean_multiple(ing.get("prep_multiple"))
        # 取整后需求为 0 的情形（散数为 0）照样留行、占量 0，不当“没有这料”删行。
        occupied = round_up_multiple(qty, multiple)
        shortage = max(0.0, occupied - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            raw_need_qty=round(qty, 3),
            prep_multiple=multiple,
            need_qty=occupied,
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
        ))
    return lines


def result_to_dict(lines: list[NeedLine]) -> dict:
    return {
        "prep_lines": [asdict(l) for l in lines],
        "shortages": [asdict(l) for l in lines if l.shortage > 0],
        "stats": {
            "ingredient_count": len(lines),
            "shortage_count": sum(1 for l in lines if l.shortage > 0),
            "total_shortage_qty": round(sum(l.shortage for l in lines), 3),
        },
    }


def apply_multiples(result: dict, ingredients: dict[int, dict]) -> dict:
    """按当前倍数栏整张重写一份已落单快照的占用列与缺料贴。

    行集合以单子为准：只改数、不增删行（取整后为 0 也留行占量 0）；
    原料档案里缺失时保持原行原样，绝不丢行。三处（备料台/缺料贴/占用列）
    数字由这里一次产出，天然同一口径。
    """
    lines = result.get("prep_lines", [])
    for line in lines:
        iid = line["ingredient_id"]
        ing = ingredients.get(iid)
        raw = float(line.get("raw_need_qty", line.get("need_qty", 0.0)))
        # 保存倍数只改栏：单子的结存冻结在落单瞬间，不从库存页刷新，只重算占用与缺料。
        stock = float(line.get("stock_qty", 0.0))
        multiple = _clean_multiple(ing.get("prep_multiple")) if ing is not None else line.get("prep_multiple")
        occupied = round_up_multiple(raw, multiple)
        line["raw_need_qty"] = round(raw, 3)
        line["prep_multiple"] = multiple
        line["need_qty"] = occupied
        line["stock_qty"] = round(stock, 3)
        line["shortage"] = round(max(0.0, occupied - stock), 3)
    result["prep_lines"] = lines
    result["shortages"] = [dict(l) for l in lines if l["shortage"] > 0]
    result["stats"] = {
        "ingredient_count": len(lines),
        "shortage_count": sum(1 for l in lines if l["shortage"] > 0),
        "total_shortage_qty": round(sum(l["shortage"] for l in lines), 3),
    }
    return result

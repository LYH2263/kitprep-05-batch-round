"""Central kitchen BOM explode: order lines × BOM qty, merge ingredients.

占用量(reserved)= 需求按起备倍数取整;缺料 = max(0, 占用 − 库存)。
取整口径全系统唯一:四舍五入到倍数的整数倍(ROUND_HALF_UP),没配倍数不取整。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP


def round_to_multiple(qty: float, multiple: float | None) -> float:
    """需求按起备倍数取整:四舍五入到倍数的整数倍。

    没配过倍数(None)不取整;倍数 <= 0 属于非法配置,同样不取整(兜底,
    正常路径在写入接口处已被拒绝)。取整结果可以是 0(如 0.39 个批次)。
    """
    if multiple is None or multiple <= 0:
        return qty
    q = Decimal(str(qty))
    m = Decimal(str(multiple))
    batches = (q / m).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return float(batches * m)


@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    reserved_qty: float
    stock_qty: float
    shortage: float
    prep_multiple: float | None


def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion.

    ingredients 每项可带 prep_multiple;缺料按取整后的占用量计算。
    取整后需求变成 0 的行保留(reserved_qty=0),不删行。
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
        multiple = ing.get("prep_multiple")
        qty = round(qty, 6)  # 先消浮点噪声,需求列与占用列同一基准
        reserved = round_to_multiple(qty, multiple)
        shortage = max(0.0, reserved - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=round(qty, 3),
            reserved_qty=round(reserved, 3),
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
            prep_multiple=multiple,
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

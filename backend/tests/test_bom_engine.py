from app.services.bom_engine import (
    NeedLine,
    apply_multiples,
    explode_and_merge,
    result_to_dict,
    round_up_multiple,
)


def _ings(multiples=None, stocks=None):
    multiples = multiples or {}
    stocks = stocks or {}
    return {
        1: {"code": "A", "name": "肉", "unit": "kg",
            "stock_qty": stocks.get(1, 1.0), "prep_multiple": multiples.get(1)},
        2: {"code": "B", "name": "米", "unit": "kg",
            "stock_qty": stocks.get(2, 5.0), "prep_multiple": multiples.get(2)},
    }


def test_explode_merge():
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.1},
        {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
    ]
    lines = explode_and_merge(order_lines, bom, _ings())
    by_id = {l.ingredient_id: l for l in lines}
    assert by_id[1].need_qty == 3.5  # 没配倍数：占用 == 散数
    assert by_id[1].raw_need_qty == 3.5
    assert by_id[1].prep_multiple is None
    assert by_id[1].shortage == 2.5
    assert by_id[2].need_qty == 1.0
    assert by_id[2].shortage == 0.0


def test_no_negative_shortage():
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    ings = {1: {"code": "A", "name": "油", "unit": "L", "stock_qty": 10.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].shortage == 0.0


def test_round_up_basic():
    assert round_up_multiple(3.2, 5) == 5.0
    assert round_up_multiple(5.0, 5) == 5.0
    assert round_up_multiple(0.2, 0.5) == 0.5
    # 没配过 / 非法倍数一律不取整
    assert round_up_multiple(3.2, None) == 3.2
    assert round_up_multiple(3.2, 0) == 3.2
    assert round_up_multiple(3.2, -1) == 3.2
    # 取整后为 0：占量 0，不删
    assert round_up_multiple(0.0, 5) == 0.0


def test_occupied_and_shortage_use_rounded_value():
    # 散数 3.5，倍数 5 → 占用 5；库存 4 → 缺料按占用算 = 1，而不是散数口径的 0
    order_lines = [{"dish_id": 1, "portions": 35}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.1}]
    ings = _ings(multiples={1: 5.0}, stocks={1: 4.0})
    lines = explode_and_merge(order_lines, bom, ings)
    line = lines[0]
    assert line.raw_need_qty == 3.5
    assert line.need_qty == 5.0
    assert line.shortage == 1.0


def test_apply_multiples_roundtrip_and_clear():
    order_lines = [{"dish_id": 1, "portions": 32}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.1}]
    ings = _ings(multiples={1: 5.0}, stocks={1: 4.0})
    result = result_to_dict(explode_and_merge(order_lines, bom, ings))
    line = result["prep_lines"][0]
    assert line["need_qty"] == 5.0 and line["shortage"] == 1.0

    # 改倍数 2：整张按散数重算 → 3.2 向上到 4
    result = apply_multiples(result, {1: {"prep_multiple": 2.0}})
    line = result["prep_lines"][0]
    assert line["raw_need_qty"] == 3.2
    assert line["need_qty"] == 4.0
    assert line["shortage"] == 0.0
    assert result["shortages"] == []  # 缺料贴同口径，不再缺
    assert result["stats"]["shortage_count"] == 0

    # 清空倍数：回到散数，行还在
    result = apply_multiples(result, {1: {"prep_multiple": None}})
    line = result["prep_lines"][0]
    assert line["need_qty"] == 3.2
    assert line["prep_multiple"] is None
    assert len(result["prep_lines"]) == 1


def test_apply_keeps_zero_need_row_and_stock():
    # 落单后某料散数为 0：必须留行、占量 0，不得当“没有这料”删行
    result = {"prep_lines": [{
        "ingredient_id": 9, "ingredient_code": "Z", "ingredient_name": "零需求",
        "unit": "kg", "raw_need_qty": 0.0, "prep_multiple": None,
        "need_qty": 0.0, "stock_qty": 3.0, "shortage": 0.0,
    }], "order": {"id": 1}}
    out = apply_multiples(result, {9: {"prep_multiple": 5.0}})
    assert len(out["prep_lines"]) == 1
    row = out["prep_lines"][0]
    assert row["need_qty"] == 0.0
    assert row["shortage"] == 0.0
    assert row["stock_qty"] == 3.0  # 结存冻结，保存倍数不刷新结存


def test_same_caliber_as_fresh_run():
    # 保存倍数重写在用单 的结果，必须等于 按当前倍数重新生成 的结果
    order_lines = [{"dish_id": 1, "portions": 33}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.1}]
    base = result_to_dict(explode_and_merge(order_lines, bom, _ings()))
    fresh = result_to_dict(explode_and_merge(
        order_lines, bom, _ings(multiples={1: 2.5}, stocks={1: 1.0})))
    rewritten = apply_multiples(base, {1: {"prep_multiple": 2.5}})
    a, b = rewritten["prep_lines"][0], fresh["prep_lines"][0]
    assert (a["need_qty"], a["shortage"]) == (b["need_qty"], b["shortage"])
    assert (a["need_qty"], a["shortage"]) == (5.0, 4.0)

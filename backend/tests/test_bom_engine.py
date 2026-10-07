from app.services.bom_engine import explode_and_merge, round_to_multiple

def test_explode_merge():
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.1},
        {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
    ]
    ings = {
        1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 1.0},
        2: {"code": "B", "name": "米", "unit": "kg", "stock_qty": 5.0},
    }
    lines = explode_and_merge(order_lines, bom, ings)
    by_id = {l.ingredient_id: l for l in lines}
    assert by_id[1].need_qty == 3.5  # 10*0.2 + 5*0.3
    assert by_id[1].shortage == 2.5
    assert by_id[1].reserved_qty == 3.5  # 没配倍数不取整,占用=需求
    assert by_id[2].need_qty == 1.0
    assert by_id[2].shortage == 0.0

def test_no_negative_shortage():
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    ings = {1: {"code": "A", "name": "油", "unit": "L", "stock_qty": 10.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].shortage == 0.0

def test_round_to_multiple_half_up():
    assert round_to_multiple(1.75, 0.5) == 2.0
    assert round_to_multiple(1.24, 0.5) == 1.0
    assert round_to_multiple(1.25, 0.5) == 1.5
    assert round_to_multiple(2.5, 5.0) == 5.0    # 半批进一批
    assert round_to_multiple(2.49, 5.0) == 0.0   # 不足半批取整为 0
    assert round_to_multiple(10.5, 0.5) == 10.5  # 已是整数倍,不动

def test_round_to_multiple_unset_or_invalid_no_rounding():
    assert round_to_multiple(1.75, None) == 1.75  # 没配过倍数则不取整
    assert round_to_multiple(1.75, 0) == 1.75     # 非法倍数兜底不取整
    assert round_to_multiple(1.75, -2) == 1.75

def test_explode_with_multiple_reserved_and_zero_row_kept():
    order_lines = [{"dish_id": 1, "portions": 7}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.25},  # need 1.75
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.28},  # need 1.96
    ]
    ings = {
        1: {"code": "A", "name": "酱", "unit": "L", "stock_qty": 1.9, "prep_multiple": 0.5},
        2: {"code": "B", "name": "油", "unit": "L", "stock_qty": 5.0, "prep_multiple": 5.0},
    }
    lines = explode_and_merge(order_lines, bom, ings)
    by_id = {l.ingredient_id: l for l in lines}
    # 占用按倍数取整,缺料 = 占用 − 库存(取整可能把缺料顶出来)
    assert by_id[1].need_qty == 1.75
    assert by_id[1].reserved_qty == 2.0
    assert by_id[1].shortage == 0.1
    # 取整后需求变成 0:必须留行、占量为 0,禁止删行
    assert by_id[2].reserved_qty == 0.0
    assert by_id[2].shortage == 0.0
    assert len(lines) == 2

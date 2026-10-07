import json

from sqlalchemy import select

from app.models.models import Ingredient, PrepRun


def _run_json(ctx, order_id):
    run = ctx["db"].scalars(
        select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id.desc())
    ).first()
    return run, json.loads(run.result_json)


def _line(data, iid):
    return next(l for l in data["prep_lines"] if l["ingredient_id"] == iid)


def _all_runs(ctx, order_id):
    return list(ctx["db"].scalars(
        select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id)
    ).all())


def test_generate_then_save_multiple_rewrites_active_sheet(ctx):
    c, ids = ctx["client"], ctx["ids"]
    # 先生成备料单（散数 3.3，未配倍数，占用=散数）
    r = c.post(f"/api/prep/run?order_id={ids['open']}")
    assert r.status_code == 200
    first_id = r.json()["id"]
    assert _line(r.json(), ids["meat"])["need_qty"] == 3.3

    # 保存倍数 5：栏写入 + 同一张单整张重写（不新建单）
    r = c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": 5})
    assert r.status_code == 200
    assert r.json()["prep_multiple"] == 5.0
    assert r.json()["rewritten_runs"] == [{"order_id": ids["open"], "run_id": first_id}]

    run, data = _run_json(ctx, ids["open"])
    assert run.id == first_id  # 没有新开单，是原单整张重写
    line = _line(data, ids["meat"])
    assert line["raw_need_qty"] == 3.3          # 散数不动
    assert line["prep_multiple"] == 5.0         # 栏新
    assert line["need_qty"] == 5.0              # 占用按新倍数取整，不是散数
    assert line["shortage"] == 1.0              # 5 - 库存4

    # 三处同一口径：备料台 /latest、缺料贴、单内占用列
    latest = c.get(f"/api/prep/latest?order_id={ids['open']}").json()
    short = c.get(f"/api/prep/shortages?order_id={ids['open']}").json()
    sl = next(s for s in short["shortages"] if s["ingredient_id"] == ids["meat"])
    assert _line(latest, ids["meat"])["need_qty"] == line["need_qty"] == sl["need_qty"] == 5.0
    assert sl["shortage"] == line["shortage"] == 1.0
    assert short["stats"]["total_shortage_qty"] >= 1.0


def test_zero_need_row_kept_with_zero_occupied(ctx):
    c, ids = ctx["client"], ctx["ids"]
    c.post(f"/api/prep/run?order_id={ids['open']}")
    r = c.put(f"/api/inventory/{ids['rice']}/multiple", json={"prep_multiple": 10})
    assert r.status_code == 200
    _, data = _run_json(ctx, ids["open"])
    rice_row = _line(data, ids["rice"])
    assert rice_row["raw_need_qty"] == 0.0
    assert rice_row["need_qty"] == 0.0      # 取整后为 0：占量 0
    assert rice_row["shortage"] == 0.0
    assert len(data["prep_lines"]) == 2     # 留行，没被当“没有这料”删掉
    assert all(s["ingredient_id"] != ids["rice"] for s in data["shortages"])


def test_stock_not_reduced_and_stock_frozen_on_sheet(ctx):
    c, ids = ctx["client"], ctx["ids"]
    c.post(f"/api/prep/run?order_id={ids['open']}")
    stock_before = ctx["db"].get(Ingredient, ids["meat"]).stock_qty
    c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": 5})
    ctx["db"].expire_all()
    assert ctx["db"].get(Ingredient, ids["meat"]).stock_qty == stock_before  # 结存不变少
    _, data = _run_json(ctx, ids["open"])
    assert _line(data, ids["meat"])["stock_qty"] == stock_before             # 单内结存冻结


def test_historical_run_not_rewritten(ctx):
    c, ids = ctx["client"], ctx["ids"]
    # 第一张单，随后再生成第二张：第一张即“已落下的旧单”
    r1 = c.post(f"/api/prep/run?order_id={ids['open']}").json()
    r2 = c.post(f"/api/prep/run?order_id={ids['open']}").json()
    assert r2["id"] > r1["id"]
    old, old_data = _run_json_at(ctx, ids["open"], r1["id"])

    r = c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": 5})
    assert r.status_code == 200
    # 最新单被重写
    _, new_data = _run_json(ctx, ids["open"])
    assert _line(new_data, ids["meat"])["need_qty"] == 5.0
    assert r.json()["rewritten_runs"][0]["run_id"] == r2["id"]

    # 历史单冻结：仍是散数、无倍数
    ctx["db"].expire_all()
    old_row = ctx["db"].get(PrepRun, r1["id"])
    old_json = json.loads(old_row.result_json)
    line = _line(old_json, ids["meat"])
    assert line["need_qty"] == 3.3
    assert line.get("prep_multiple") is None


def _run_json_at(ctx, order_id, run_id):
    run = ctx["db"].get(PrepRun, run_id)
    return run, json.loads(run.result_json)


def test_closed_order_active_sheet_not_rewritten(ctx):
    c, ids = ctx["client"], ctx["ids"]
    c.post(f"/api/prep/run?order_id={ids['closed']}")
    c.post(f"/api/prep/run?order_id={ids['open']}")
    r = c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": 5})
    assert r.status_code == 200
    # 只重写 open 订单的在用单，closed 的单不碰
    assert [x["order_id"] for x in r.json()["rewritten_runs"]] == [ids["open"]]
    _, closed_data = _run_json(ctx, ids["closed"])
    assert _line(closed_data, ids["meat"])["need_qty"] == 3.3


def test_invalid_multiple_everything_stays(ctx):
    c, ids = ctx["client"], ctx["ids"]
    c.post(f"/api/prep/run?order_id={ids['open']}")
    before_run, before = _run_json(ctx, ids["open"])
    for bad in (0, -3, -0.01):
        r = c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": bad})
        assert r.status_code == 400
    for bad in ("abc",):
        r = c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": bad})
        assert r.status_code in (400, 422)
    # 栏停在写入前
    ctx["db"].expire_all()
    assert ctx["db"].get(Ingredient, ids["meat"]).prep_multiple is None
    # 单与缺料贴停在写入前（占用仍是散数）
    run, data = _run_json(ctx, ids["open"])
    assert run.id == before_run.id
    assert _line(data, ids["meat"])["need_qty"] == 3.3
    assert _line(data, ids["meat"]).get("prep_multiple") is None


def test_clear_multiple_returns_to_raw(ctx):
    c, ids = ctx["client"], ctx["ids"]
    c.post(f"/api/prep/run?order_id={ids['open']}")
    c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": 5})
    _, rounded = _run_json(ctx, ids["open"])
    assert _line(rounded, ids["meat"])["need_qty"] == 5.0
    # 清空倍数：栏回 None，在用单整张回到散数
    r = c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": None})
    assert r.status_code == 200
    assert r.json()["prep_multiple"] is None
    ctx["db"].expire_all()
    _, data = _run_json(ctx, ids["open"])
    line = _line(data, ids["meat"])
    assert line["prep_multiple"] is None
    assert line["need_qty"] == 3.3


def test_regenerate_after_save_same_caliber(ctx):
    c, ids = ctx["client"], ctx["ids"]
    c.post(f"/api/prep/run?order_id={ids['open']}")
    c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": 2})
    # 备料台再生成一张新单：与倍数保存重写的占用/缺料同一口径
    rewritten, rewritten_data = _run_json(ctx, ids["open"])
    rl = _line(rewritten_data, ids["meat"])
    fresh = c.post(f"/api/prep/run?order_id={ids['open']}").json()
    fl = _line(fresh, ids["meat"])
    assert (fl["raw_need_qty"], fl["need_qty"], fl["shortage"], fl["prep_multiple"]) == \
           (rl["raw_need_qty"], rl["need_qty"], rl["shortage"], rl["prep_multiple"])
    assert fl["need_qty"] == 4.0  # 3.3 向上到 2 的倍数 = 4


def test_save_without_any_run_only_sets_column(ctx):
    c, ids = ctx["client"], ctx["ids"]
    r = c.put(f"/api/inventory/{ids['meat']}/multiple", json={"prep_multiple": 5})
    assert r.status_code == 200
    assert r.json()["rewritten_runs"] == []
    ctx["db"].expire_all()
    assert ctx["db"].get(Ingredient, ids["meat"]).prep_multiple == 5.0
    # 没有因此冒出单子
    assert ctx["db"].scalars(select(PrepRun)).all() == []


def test_run_only_creates_sheet_does_not_change_stock(ctx):
    c, ids = ctx["client"], ctx["ids"]
    stock_before = ctx["db"].get(Ingredient, ids["meat"]).stock_qty
    c.post(f"/api/prep/run?order_id={ids['open']}")
    ctx["db"].expire_all()
    assert ctx["db"].get(Ingredient, ids["meat"]).stock_qty == stock_before  # 出单不动结存

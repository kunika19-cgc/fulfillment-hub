"""Workflow tests. Run from the project folder:  pytest -q"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

import store
from logic import enrich

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def load():
    return AppTest.from_file(APP, default_timeout=90).run()


def W(at):
    return at.session_state["world"]


def btn(at, label=None, startswith=None):
    return next(b for b in at.button if (b.label == label if label else b.label.startswith(startswith)))


def start(at):
    """Warehouse: the current worker presses 'Start next order'. Returns (order id, product row)."""
    btn(at, startswith="Start next order").click().run()
    w = W(at)
    worker = at.radio(key="worker").value
    oid = w["orders"].query("status == 'label_ready' and picker == @worker").order_id.iloc[0]
    o = w["orders"].set_index("order_id").loc[oid]
    return oid, w["products"].set_index("sku").loc[o.sku]


def scan(at, code):
    next(t for t in at.text_input if t.label == "Item barcode").set_value(code)
    btn(at, "Check item").click().run()


def test_app_loads_with_all_six_tabs():
    at = load()
    labels = [t.label for t in at.tabs]
    assert not at.exception
    for name in ("Office board", "Warehouse", "Courier pickup", "Stock", "Issues", "Insights"):
        assert any(name in l for l in labels), name


def test_demo_shows_late_and_at_risk_orders():
    at = load()
    html = " ".join(m.value for m in at.markdown)
    assert 'class="kpi red"' in html and 'class="oc red"' in html


def test_start_next_order_gives_the_most_urgent_one_to_this_worker():
    at = load()
    oid, _ = start(at)
    o = W(at)["orders"].set_index("order_id")
    assert o.loc[oid, "picker"] == "Asha"
    ready = o[(o.status == "label_ready") & o.picker.isna()]
    assert not (ready.is_priority & ~o.loc[oid, "is_priority"]).any() or o.loc[oid, "is_priority"]


def test_two_workers_never_get_the_same_order():
    a, b = load(), load()
    oid_a, _ = start(a)
    b.radio(key="worker").set_value("Ravi").run()
    oid_b, _ = start(b)
    assert oid_a != oid_b and not a.exception and not b.exception


def test_wrong_barcode_is_blocked_and_logged():
    at = load()
    _, p = start(at)
    family = W(at)["products"].query("name == @p['name']")
    wrong = family[family.variant != p.variant].barcode.iloc[0]
    n = len(W(at)["issues"])
    scan(at, wrong)
    assert len(W(at)["issues"]) == n + 1 and not at.exception
    assert "WRONG VARIANT" in " ".join(m.value for m in at.markdown)


def test_unknown_barcode_is_not_accepted_and_not_logged_as_wrong_variant():
    at = load()
    start(at)
    n = len(W(at)["issues"])
    scan(at, "000")
    assert len(W(at)["issues"]) == n and "not recognised" in " ".join(m.value for m in at.markdown)


def test_tap_fallback_also_blocks_a_wrong_variant():
    at = load()
    _, p = start(at)
    wrong = next(v for v in W(at)["products"].query("name == @p['name']").variant if v != p.variant)
    n = len(W(at)["issues"])
    btn(at, wrong).click().run()
    assert len(W(at)["issues"]) == n + 1


def test_scan_correct_item_then_pack_moves_order_to_staged_with_slot_and_stock_drops():
    at = load()
    oid, p = start(at)
    before = int(W(at)["products"].set_index("sku").loc[p.name, "main_stock"])
    scan(at, p.barcode)
    for c in at.checkbox:
        c.check()
    at.run()
    btn(at, startswith="Packed").click().run()
    row = W(at)["orders"].set_index("order_id").loc[oid]
    assert row.status == "staged" and isinstance(row.slot, str)
    assert int(W(at)["products"].set_index("sku").loc[p.name, "main_stock"]) == before - row.qty


def test_missed_courier_orders_can_be_rebooked():
    at = load()
    btn(at, startswith="Re-book").click().run()
    assert not at.exception and any(i["type"] == "Courier" for i in W(at)["issues"])


def test_receiving_adds_stock_and_logs_discrepancy():
    at = load()
    before = W(at)["products"].main_stock.sum()
    next(n for n in at.number_input if n.label == "Damaged").set_value(2).run()
    btn(at, "Put away on shelves").click().run()
    assert W(at)["products"].main_stock.sum() == before + 47 - 2
    assert any(i["type"] == "Receiving" for i in W(at)["issues"])


def test_track_order_shows_timeline():
    at = load()
    next(t for t in at.text_input if t.label == "Order ID").set_value("xy-1088").run()
    assert 'class="tls' in " ".join(m.value for m in at.markdown)


def test_office_can_create_a_label_with_a_chosen_courier():
    at = load()
    n = int((W(at)["orders"].status == "label_ready").sum())
    btn(at, "Create label").click().run()
    assert not at.exception
    assert int((W(at)["orders"].status == "label_ready").sum()) == n + 1


def test_a_label_made_on_one_screen_shows_up_on_another():
    """The big one: office and warehouse are different browsers but share one truth."""
    office, warehouse = load(), load()
    before = int((W(warehouse)["orders"].status == "label_ready").sum())
    btn(office, "Create label").click().run()
    warehouse.run()   # the warehouse user clicks / refreshes
    assert int((W(warehouse)["orders"].status == "label_ready").sum()) == before + 1


def test_data_survives_a_page_refresh_and_reset_clears_it():
    at = load()
    btn(at, "Create label").click().run()
    n = int((W(at)["orders"].status == "label_ready").sum())
    fresh = load()   # a brand-new browser session
    assert int((W(fresh)["orders"].status == "label_ready").sum()) == n
    btn(fresh, "Reset demo for everyone").click().run()
    assert int((W(fresh)["orders"].status == "label_ready").sum()) != n


# ---------------- Fulfillment Hub additions ----------------
def edit_db(change):
    """Change the shared world directly (like a teammate would), then the next screen load sees it."""
    w = store.load()
    change(w)
    store.save(w)


def top_free_order(w):
    o = enrich(w)
    r = o[(o.status == "label_ready") & o.picker.isna() & ~o.waiting_transfer & ~o.on_hold].sort_values(["is_priority", "mins_left"], ascending=[False, True])
    return r.iloc[0]


def test_capacity_panel_shows_a_gap_and_more_workers_closes_it():
    at = load()
    html = " ".join(m.value for m in at.markdown)
    assert "Capacity check" in html and "-order gap" in html
    at.number_input(key="workers_on").set_value(10).run()
    assert "-order gap" not in " ".join(m.value for m in at.markdown)


def test_stock_only_in_warehouse_2_becomes_a_transfer_task_and_the_picker_moves_on():
    at = load()
    top = top_free_order(W(at))
    def stuck(w):
        p = w["products"]
        p.loc[p.sku == top.sku, ["main_stock", "second_stock"]] = [0, 40]
    edit_db(stuck)
    at = load()
    btn(at, startswith="Start next order").click().run()
    w = W(at)
    assert any(x["order"] == top.order_id and not x["done"] for x in w["transfers"])
    assert w["orders"].set_index("order_id").loc[top.order_id, "picker"] is None      # nobody is stuck holding it
    assert "Waiting for transfer" in " ".join(m.value for m in at.markdown)
    # the stock arrives -> order is back in the normal queue
    before = int(w["products"].set_index("sku").loc[top.sku, "main_stock"])
    btn(at, startswith="Stock arrived").click().run()
    assert int(W(at)["products"].set_index("sku").loc[top.sku, "main_stock"]) > before
    assert not any(not x["done"] for x in W(at)["transfers"])


def test_item_not_found_puts_the_order_on_hold_and_alerts_the_office():
    at = load()
    oid, p = start(at)
    btn(at, startswith="Can't find it").click().run()
    w = W(at)
    assert any(i["type"] == "Stock" and i["order"] == oid and i["open"] for i in w["issues"])
    assert int(w["products"].set_index("sku").loc[p.name, "main_stock"]) == 0
    assert w["orders"].set_index("order_id").loc[oid, "picker"] is None
    assert "Reported to the office" in " ".join(m.value for m in at.success)
    assert enrich(w).set_index("order_id").loc[oid, "on_hold"]
    assert "Warehouse reported" in " ".join(m.value for m in at.markdown)       # the office board shows the alert
    btn(at, startswith="Start next order").click().run()                          # and the same order is not handed out again
    assert W(at)["orders"].set_index("order_id").loc[oid, "picker"] is None


def test_known_look_alike_pair_gets_the_extra_loud_warning():
    at = load()
    cot = W(at)["products"].sku.iloc[1]
    def give_cotton_tee(w):
        o = w["orders"]
        top = top_free_order(w)
        o.loc[o.order_id == top.order_id, ["sku", "qty", "picker"]] = [cot, 1, "Asha"]
        w["products"].loc[w["products"].sku == cot, "main_stock"] = 50
    edit_db(give_cotton_tee)
    at = load()
    assert "CONFUSABLE ITEMS" in " ".join(m.value for m in at.markdown)


def test_a_wrong_scan_is_remembered_as_a_mixup():
    at = load()
    _, p = start(at)
    n = len(W(at)["confusions"])
    family = W(at)["products"].query("name == @p['name']")
    scan(at, family[family.variant != p.variant].barcode.iloc[0])
    assert len(W(at)["confusions"]) == n + 1


def test_hindi_toggle_switches_the_warehouse_screen():
    at = load()
    at.radio(key="lang").set_value("हिन्दी").run()
    html = " ".join(m.value for m in at.markdown)
    assert "पिक सूची" in html and not at.exception
    btn(at, startswith="अगला ऑर्डर शुरू करें").click().run()
    assert "चीज़ जाँचें" in " ".join(b.label for b in at.button)
    p = W(at)["products"].set_index("sku").loc[W(at)["orders"].query("picker == 'Asha'").sku.iloc[0]]
    family = W(at)["products"].query("name == @p['name']")
    next(t for t in at.text_input if t.label == "Item barcode").set_value(family[family.variant != p.variant].barcode.iloc[0])
    btn(at, "चीज़ जाँचें").click().run()
    assert "आपको" in " ".join(m.value for m in at.markdown) and not at.exception     # plain-language "you need X"


def test_insights_shows_the_four_success_metrics_and_the_tour_banner():
    at = load()
    html = " ".join(m.value for m in at.markdown)
    for label in ("On-time ship rate", "Wrong-item near-misses", "Stock-out picks", "Missed pickups", "2-minute tour"):
        assert label in html, label
    assert not at.exception

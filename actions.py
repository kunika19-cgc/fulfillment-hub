"""actions.py - everything that CHANGES the world (create label, pack, re-book, hand over, move stock).
Kept apart from the screens so each rule can be tested without a browser.
Step numbers used in world["events"]: 0 received, 1 label, 2 picked & packed, 3 staged, 4 shipped.
"""
from datetime import datetime

import pandas as pd

from logic import DONE, next_slot


def _now(now):
    return now or datetime.now()


def log_issue(world, kind, order_id, text, owner, now=None):
    """Every problem is written down with an owner, so nothing is forgotten."""
    new_id = max([i["id"] for i in world["issues"]], default=0) + 1
    world["issues"].insert(0, {"id": new_id, "type": kind, "order": order_id, "text": text, "owner": owner,
                               "open": True, "time": _now(now).strftime("%H:%M")})


def record(world, order_id, step, now=None):
    """Remember the real time an order reached a step (feeds the 'track any order' timeline)."""
    world["events"].setdefault(order_id, {})[step] = _now(now)


def create_label(world, order_id, courier, now=None):
    """Returns False (and changes nothing) if someone else already labelled this order."""
    m = world["orders"].order_id == order_id
    if not m.any() or world["orders"].loc[m, "status"].iloc[0] != "new":
        return False
    world["orders"].loc[m, "status"] = "label_ready"
    world["orders"].loc[m, "courier"] = courier
    record(world, order_id, 1, now)
    return True


def record_confusion(world, expected_sku, scanned_sku):
    """Remember that these two look-alike items were mixed up. After CONFUSE_AFTER times they become 'confusable'."""
    if expected_sku != scanned_sku:
        world["confusions"].append([expected_sku, scanned_sku])


def claim_order(world, order_id, worker):
    """A worker takes an order. Returns False if a teammate already has it, so two people
    never pick the same order."""
    o = world["orders"]
    m = o.order_id == order_id
    if not m.any() or o.loc[m, "status"].iloc[0] != "label_ready":
        return False
    holder = o.loc[m, "picker"].iloc[0]
    if pd.notna(holder) and holder != worker:
        return False
    o.loc[m, "picker"] = worker
    return True


def release_order(world, order_id):
    """Put an order back in the shared queue (e.g. the worker cannot continue)."""
    o = world["orders"]
    o.loc[o.order_id == order_id, "picker"] = None


def pack_order(world, order_id, now=None):
    """Order is packed and staged: take the items off the shelf count and give the box a slot.
    Returns the staging slot, e.g. 'B-04'."""
    now = _now(now)
    orders, prod = world["orders"], world["products"]
    m = orders.order_id == order_id
    row = orders[m].iloc[0]
    if row["status"] in DONE:   # double-click / two screens: never take stock off the shelf twice
        return None
    slot = next_slot(orders, world["couriers"], row["courier"])
    orders.loc[m, "status"] = "staged"
    orders.loc[m, "staged_at"] = now
    orders.loc[m, "slot"] = slot
    pm = prod.sku == row["sku"]
    prod.loc[pm, "main_stock"] = max(int(prod.loc[pm, "main_stock"].iloc[0]) - int(row["qty"]), 0)
    record(world, order_id, 2, now)
    record(world, order_id, 3, now)
    return slot


def rebook(world, order_ids, courier, now=None):
    """Move orders to another courier. Boxes that are already staged are moved to the new lane."""
    orders = world["orders"]
    ids = list(order_ids)
    orders.loc[orders.order_id.isin(ids), "courier"] = courier
    for oid in ids:
        m = orders.order_id == oid
        if orders.loc[m, "status"].iloc[0] == "staged":
            orders.loc[m, "slot"] = None  # free the old slot first so numbering stays correct
            orders.loc[m, "slot"] = next_slot(orders, world["couriers"], courier)
    log_issue(world, "Courier", "-", f"{len(ids)} orders re-booked to {courier}", "Office", now)


def handover(world, courier, missing_ids=(), now=None):
    """Courier collects the boxes staged in its lane. Boxes the team could not find in the lane
    stay staged and are logged as an issue instead of silently disappearing.
    Returns (number shipped, list of missing order ids)."""
    now = _now(now)
    orders = world["orders"]
    missing = set(missing_ids)
    staged = orders[(orders.status == "staged") & (orders.courier == courier)]
    for r in staged.itertuples():
        if r.order_id in missing:
            log_issue(world, "Courier", r.order_id,
                      f"Box not found in lane at {courier} handover (slot {r.slot}) - search the warehouse", "Warehouse", now)
    ship = staged[~staged.order_id.isin(missing)].order_id.tolist()
    orders.loc[orders.order_id.isin(ship), "status"] = "shipped"
    for oid in ship:
        record(world, oid, 4, now)
    return len(ship), sorted(missing & set(staged.order_id))


def move_stock(world, sku, n):
    """Warehouse 2 -> main warehouse."""
    p = world["products"]
    m = p.sku == sku
    n = min(int(n), int(p.loc[m, "second_stock"].iloc[0]))
    p.loc[m, "main_stock"] += n
    p.loc[m, "second_stock"] -= n
    return n


REQUIRED_COLUMNS = ["order_id", "channel", "sku", "qty"]   # "priority" (yes/no) is optional


def import_orders(world, df, now=None):
    """Add new orders from a spreadsheet export (CSV). XYZ lives in spreadsheets today, so this is the
    bridge: nothing is half-imported - if any row is bad, NOTHING is added and every problem is listed.
    Returns (number added, list of problems)."""
    now = _now(now)
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return 0, [f"Missing column(s): {', '.join(missing)}"]
    orders, prod = world["orders"], world["products"]
    problems, seen = [], set()
    for i, r in df.iterrows():
        line, oid = i + 2, str(r["order_id"]).strip()
        if not oid or oid == "nan":
            problems.append(f"Row {line}: order_id is empty")
        elif oid in set(orders.order_id) or oid in seen:
            problems.append(f"Row {line}: order {oid} already exists")
        seen.add(oid)
        if str(r["sku"]).strip() not in set(prod.sku):
            problems.append(f"Row {line}: unknown SKU '{r['sku']}'")
        try:
            if int(r["qty"]) < 1:
                raise ValueError
        except (TypeError, ValueError):
            problems.append(f"Row {line}: qty must be a whole number of 1 or more")
    if problems or df.empty:
        return 0, problems or ["The file has no rows"]
    pri = df["priority"].astype(str).str.strip().str.lower().isin(["yes", "y", "true", "1"]) if "priority" in df else False
    new = pd.DataFrame({
        "order_id": df.order_id.astype(str).str.strip(), "channel": df.channel.astype(str).str.strip(),
        "sku": df.sku.astype(str).str.strip(), "qty": df.qty.astype(int), "is_priority": pri,
        "status": "new", "courier": None, "created_at": now, "staged_at": pd.NaT, "slot": None, "picker": None,
    })
    for c in ("courier", "slot", "picker"):
        new[c] = new[c].astype("object")
    world["orders"] = pd.concat([orders, new], ignore_index=True)
    return len(new), []

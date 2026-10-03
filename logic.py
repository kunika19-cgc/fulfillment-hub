"""logic.py - the 'brain': deadlines, order health, stock reservation, courier choice, delay risk.
No screens here. The app (app.py) only displays what this file computes.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

SLA_BUFFER_MIN = 20   # a box must be STAGED this many minutes before the courier arrives
AT_RISK_MIN = 30      # under this many minutes left = "at risk"
DONE = ["staged", "shipped"]

# Typical handling times (minutes). Used to ask: "is there enough time left to do the remaining work?"
LABEL_MIN = 5         # office creates the label
PICKPACK_MIN = 12     # warehouse picks, verifies and packs
TRANSFER_MIN = 30     # moving stock over from Warehouse 2
PER_ORDER_MIN = 4     # hands-on minutes per order per worker (capacity check). Assumption - tune it here.
CONFUSE_AFTER = 2     # a pair of look-alike items mixed up this many times is flagged "confusable"


def courier_left(couriers, elapsed):
    """Minutes until each courier leaves (negative = already gone)."""
    return couriers.set_index("courier")["cutoff_min"] - elapsed


def recommend_courier(couriers, elapsed, is_priority):
    """Pick a sensible default courier for an order that has no label yet.
    Priority -> fastest courier that can still be caught.
    Standard -> cheapest courier promising 2 days or better that can still be caught.
    The office can always override this."""
    avail = couriers[couriers.cutoff_min - elapsed > SLA_BUFFER_MIN]
    if avail.empty:  # everyone has left: the one leaving last is the least bad option
        return couriers.sort_values("cutoff_min").iloc[-1]["courier"]
    if is_priority:
        return avail.sort_values(["days", "cost_inr"]).iloc[0]["courier"]
    pool = avail[avail.days <= 2]
    pool = pool if not pool.empty else avail
    return pool.sort_values(["cost_inr", "days"]).iloc[0]["courier"]


def lookup_barcode(products, code):
    """Find the product whose printed barcode matches what the worker scanned (None if unknown)."""
    hit = products[products.barcode == str(code).strip()]
    return None if hit.empty else hit.iloc[0]


def next_slot(orders, couriers, courier):
    """Next free staging slot in the courier's lane, e.g. 'B-04'."""
    lane = couriers.set_index("courier")["lane"][courier]
    used = orders.loc[(orders.status == "staged") & orders.slot.notna(), "slot"]
    nums = [int(s.split("-")[1]) for s in used if str(s).startswith(lane + "-")]
    return f"{lane}-{max(nums, default=0) + 1:02d}"


def enrich(world, now=None):
    """Take raw orders and add everything the screens need. Returns a new DataFrame.
    `now` is the real clock, so countdowns keep moving while the app is open."""
    now = now or datetime.now()
    start = world["now"]
    elapsed = (now - start).total_seconds() / 60
    cs = world["couriers"]
    prod = world["products"][["sku", "name", "variant", "bin", "main_stock", "second_stock"]]

    o = world["orders"].merge(prod, on="sku", how="left")  # how="left" keeps order rows in place
    o["item"] = o["name"] + " · " + o["variant"]

    # Orders the pickers should NOT be handed right now: stock is on its way from Warehouse 2,
    # or the warehouse reported the item missing (an open Stock issue). Everyone else gets them first.
    o["waiting_transfer"] = o.order_id.isin({x["order"] for x in world["transfers"] if not x["done"]})
    o["on_hold"] = o.order_id.isin({i["order"] for i in world["issues"] if i["open"] and i["type"] == "Stock"})

    # Orders without a label yet get the recommended courier (office can override at label time)
    rec = {True: recommend_courier(cs, elapsed, True), False: recommend_courier(cs, elapsed, False)}
    guess = pd.Series([rec[bool(p)] for p in o.is_priority], index=o.index)
    o["assigned_courier"] = o["courier"].fillna(guess)

    # Deadline = courier cutoff minus the safety buffer
    cutoff = cs.set_index("courier")["cutoff_min"]
    o["deadline"] = start + pd.to_timedelta(o.assigned_courier.map(cutoff) - SLA_BUFFER_MIN, unit="min")
    o["mins_left"] = ((o["deadline"] - now).dt.total_seconds() // 60).astype(int)

    is_done = o.status.isin(DONE)

    # Health: one label per order so the board can colour it
    o["health"] = np.select(
        [is_done, o.mins_left < 0, o.mins_left < AT_RISK_MIN],
        ["done", "late", "at_risk"],
        default="ok",
    )

    # ---- Stock reservation ----
    # Open orders claim stock in the order they should be handled (priority first, then closest
    # deadline). An order is "short" if the orders ahead of it plus itself need more than the shelf holds.
    o["reserved_ahead"] = 0
    o["need_cum"] = 0
    open_o = o[~is_done].sort_values(["is_priority", "mins_left", "created_at"], ascending=[False, True, True])
    cum = open_o.groupby("sku")["qty"].cumsum()
    o.loc[open_o.index, "need_cum"] = cum
    o.loc[open_o.index, "reserved_ahead"] = cum - open_o["qty"]
    o["stock_short"] = (~is_done) & (o.need_cum > o.main_stock)
    o["cant_pick"] = (~is_done) & (o.main_stock < o.qty)              # physically not enough on the shelf right now
    o["shortfall"] = np.where(o.stock_short, o.need_cum - o.main_stock, 0)
    o["avail_anywhere"] = (o.main_stock + o.second_stock) >= o.need_cum
    impossible = o.stock_short & ~o.avail_anywhere

    # ---- Delay risk: is there enough time left for the work that is still to do? ----
    work = np.where(o.status == "new", LABEL_MIN + PICKPACK_MIN, PICKPACK_MIN)
    work = work + np.where(o.stock_short & o.avail_anywhere, TRANSFER_MIN, 0)
    o["work_min"] = work
    slack = o.mins_left - work                                        # spare minutes (negative = won't make it)
    risk = 1 / (1 + np.exp(slack / 10))                               # 0 spare min -> 50%, 30 spare -> 5%
    risk = np.where(impossible, np.maximum(risk, 0.9), risk)
    risk = np.where(o.health == "late", 1.0, risk)
    o["risk"] = np.where(is_done, 0.0, risk)

    # One plain-English reason per order
    o["main_reason"] = np.select(
        [is_done, o.health == "late", impossible, o.stock_short, (o.risk >= 0.25) & (o.status == "new"), o.risk >= 0.25],
        ["", "deadline already passed", "stock not available anywhere - reorder",
         "waiting for stock from Warehouse 2", "label + pick + pack may not fit in time left",
         "pick + pack may not fit in time left"],
        default="on track",
    )
    o.loc[o.waiting_transfer & ~is_done, "main_reason"] = "waiting for transfer from Warehouse 2"
    o.loc[o.on_hold & ~is_done, "main_reason"] = "item not found on shelf - on hold, see Issues"
    return o


def capacity(o, world, workers, now=None):
    """Per courier pickup: can the team finish every open order in the time left?
    needed time = open orders x PER_ORDER_MIN / workers   vs   minutes left until the ship-by deadline.
    Returns one row per courier (earliest pickup first)."""
    now = now or datetime.now()
    el = (now - world["now"]).total_seconds() / 60
    open_o = o[~o.status.isin(DONE)]
    rows = []
    for c in world["couriers"].sort_values("cutoff_min").itertuples():
        n = int((open_o.assigned_courier == c.courier).sum())
        avail = c.cutoff_min - el - SLA_BUFFER_MIN              # working minutes left before the deadline
        can = int(max(avail, 0) * workers / PER_ORDER_MIN)       # orders the team can still finish
        gap = max(n - can, 0)
        left = c.cutoff_min - el <= 0
        need = int(np.ceil(n * PER_ORDER_MIN / avail)) if avail > 0 and n else None   # workers needed to close the gap
        status = "left" if left else "gap" if gap else "tight" if n and n > 0.8 * can else "ok"
        rows.append({"courier": c.courier, "pickup_at": world["now"] + timedelta(minutes=float(c.cutoff_min)), "open_n": n,
                     "mins_avail": int(max(avail, 0)), "can_do": can, "gap": gap, "workers_needed": need,
                     "spare": can - n, "status": status})
    out = pd.DataFrame(rows)
    # advice: the nearest LATER courier that has room for the whole gap
    out["shift_to"] = None
    for i, r in out.iterrows():
        if r.status in ("gap", "left") and r.open_n:
            need_room = r.open_n if r.status == "left" else r.gap
            later = out.loc[out.index > i]
            ok = later[(later.status != "left") & (later.spare >= need_room)]
            out.at[i, "shift_to"] = ok.courier.iloc[0] if len(ok) else None
    return out


def confusable(world):
    """sku -> list of look-alike skus it keeps getting mixed up with (pairs wrongly scanned CONFUSE_AFTER+ times)."""
    counts = {}
    for a, b in world["confusions"]:
        key = tuple(sorted((a, b)))
        counts[key] = counts.get(key, 0) + 1
    out = {}
    for (a, b), n in counts.items():
        if n >= CONFUSE_AFTER:
            out.setdefault(a, []).append(b)
            out.setdefault(b, []).append(a)
    return out


def success_metrics(o, world, now=None):
    """The four numbers XYZ would track to know the app is working (all computed live from the data)."""
    now = now or datetime.now()
    el = (now - world["now"]).total_seconds() / 60
    done = o[o.status.isin(DONE)]
    late_open = int(((~o.status.isin(DONE)) & (o.health == "late")).sum())
    on_time_done = int((done.staged_at.isna() | (done.staged_at <= done.deadline)).sum())
    gone = set(world["couriers"][world["couriers"].cutoff_min < el].courier)
    missed = int(((o.status != "shipped") & o.assigned_courier.isin(gone)).sum())
    return {
        "on_time_rate": on_time_done / max(len(done) + late_open, 1),   # finished by the ship-by deadline / (finished + already late)
        "near_misses": sum(1 for i in world["issues"] if i["type"] == "Wrong variant"),
        "stock_out_picks": int(((~o.status.isin(DONE)) & o.cant_pick).sum()),
        "missed_pickups": missed,
    }


def courier_performance(o, world, now=None):
    """Per courier: how many orders, how many beat the ship-by deadline, how many are open and in trouble.
    on_time_rate uses the same rule as success_metrics: finished by the deadline / (finished + already late).
    Returns one row per courier that has orders (read-only: changes nothing)."""
    now = now or datetime.now()
    el = (now - world["now"]).total_seconds() / 60
    gone = set(world["couriers"][world["couriers"].cutoff_min < el].courier)
    rows = []
    for c in world["couriers"].sort_values("cutoff_min").courier:
        mine = o[o.assigned_courier == c]
        if mine.empty:
            continue
        done = mine[mine.status.isin(DONE)]
        open_o = mine[~mine.status.isin(DONE)]
        on_time = int((done.staged_at.isna() | (done.staged_at <= done.deadline)).sum())
        late = int((open_o.health == "late").sum())
        rows.append({"courier": c, "orders": len(mine), "done": len(done), "on_time": on_time,
                     "open": len(open_o), "at_risk": int((open_o.health == "at_risk").sum()), "late": late,
                     "left": c in gone, "on_time_rate": on_time / max(len(done) + late, 1)})
    return pd.DataFrame(rows)


def stage_breakdown(o):
    """Where are the open orders stuck? One stage per open order, split by colour (ok / at risk / late).
    Order of stages = order of the process, so the chart reads left to right like the workflow."""
    open_o = o[~o.status.isin(DONE)].copy()
    open_o["stage"] = np.select(
        [open_o.on_hold, open_o.waiting_transfer, open_o.status == "new"],
        ["Item not found (on hold)", "Waiting for Warehouse 2 stock", "Needs label (office)"],
        default="Needs pick & pack (warehouse)",
    )
    order = ["Needs label (office)", "Needs pick & pack (warehouse)", "Waiting for Warehouse 2 stock", "Item not found (on hold)"]
    g = open_o.groupby(["stage", "health"]).size().unstack(fill_value=0).reindex(order, fill_value=0)
    for col in ("ok", "at_risk", "late"):
        if col not in g.columns:
            g[col] = 0
    g = g[["ok", "at_risk", "late"]]
    g["total"] = g.sum(axis=1)
    g["problem"] = g.at_risk + g.late
    return g.reset_index()


def top_bottleneck(o):
    """One sentence for the office: which stage holds the most at-risk or late orders right now."""
    g = stage_breakdown(o)
    total_problem = int(g.problem.sum())
    if total_problem == 0:
        return {"stage": None, "problem": 0, "share": 0.0, "text": "No open order is at risk or late right now."}
    top = g.sort_values("problem", ascending=False).iloc[0]
    share = float(top.problem) / total_problem
    return {"stage": top.stage, "problem": int(top.problem), "share": share,
            "text": f"{share * 100:.0f}% of the {total_problem} at-risk or late orders are stuck at: {top.stage}."}


def due_text(row):
    """'12m late' / '25m left' / '✔ done' - the text the board shows."""
    if row.health == "done":
        return "✔ done"
    return f"{-row.mins_left}m late" if row.mins_left < 0 else f"{row.mins_left}m left"


def kpis(o):
    open_o = o[o.status != "shipped"]
    todo = open_o[~open_o.status.isin(DONE)]
    return {
        "open": len(open_o),
        "late": int((todo.health == "late").sum()),
        "at_risk": int((todo.health == "at_risk").sum()),
        "priority_open": int(todo.is_priority.sum()),
        "blocked": int(todo.stock_short.sum()),
    }


if __name__ == "__main__":  # quick self-check: python logic.py
    from data import make_world

    w = make_world()
    o = enrich(w)
    print(kpis(o), "\n")
    cols = ["order_id", "item", "status", "assigned_courier", "mins_left", "health", "risk", "main_reason"]
    print(o[~o.status.isin(DONE)].sort_values("risk", ascending=False)[cols].head(8).to_string())
    print(o[~o.status.isin(DONE)].main_reason.value_counts())

"""app.py - the screens. All numbers come from logic.py, every change goes through actions.py,
all data from data.py.
Run with:  streamlit run app.py
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

import store
import ui
from i18n import HINDI, t
from actions import (claim_order, create_label, handover, import_orders, log_issue, move_stock, pack_order,
                     rebook, record_confusion, release_order)
from data import WORKERS, make_world
from logic import (AT_RISK_MIN, DONE, LABEL_MIN, PICKPACK_MIN, SLA_BUFFER_MIN, TRANSFER_MIN,
                   PER_ORDER_MIN, capacity, confusable, courier_performance, due_text, enrich, kpis, lookup_barcode,
                   next_slot, stage_breakdown, success_metrics, top_bottleneck)

st.set_page_config(page_title="Fulfillment Hub", page_icon="📦", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)

# ---- The world lives in a shared SQLite file (store.py), so office and warehouse see the SAME data. ----
world = store.load()
if world is None:
    world = make_world()
    store.save(world)
st.session_state["world"] = world  # only so tests / debugging can look at it
orders = enrich(world)  # recomputed on every click (it's fast) - uses the real clock


def go():
    """Save every change to the shared file, then redraw. Every button that changes data ends with this."""
    store.save(world)
    st.rerun()


def notify(msg, icon="✅"):
    """Show a small pop-up message after the next screen refresh."""
    st.session_state["_toast"] = (msg, icon)


def elapsed():
    """Minutes since the app started. Courier cut-offs are measured on this clock."""
    return (datetime.now() - world["now"]).total_seconds() / 60


FLAG = {"late": "🔴", "at_risk": "🟠", "ok": "🟢", "done": "✅"}


def style(f, h=300):
    f.update_layout(height=h, margin=dict(l=10, r=10, t=45, b=10), paper_bgcolor="white", plot_bgcolor="white", legend_title=None)
    return f


# =====================================================================================
# OFFICE
# =====================================================================================
def office_queue():
    """The office's main job: give every new order a label and a courier."""
    new = orders[orders.status == "new"].sort_values(["is_priority", "mins_left"], ascending=[False, True])
    cs, el = world["couriers"], elapsed()
    info = cs.set_index("courier")
    with st.container(border=True):
        st.markdown(f'<div class="sec">📝 Office queue · {len(new)} orders need a shipping label</div>'
                    f'<div class="sub">Priority first. The suggested courier is the fastest one still reachable for priority orders and the cheapest 2-day option for the rest.</div>',
                    unsafe_allow_html=True)
        if new.empty:
            st.success("🎉 All caught up - every order has a label. The warehouse can start picking.")
            return
        c1, c2, c3 = st.columns([3, 3, 1.3])
        rows = {r.order_id: r for r in new.itertuples()}
        pick = c1.selectbox("Order", list(rows), label_visibility="collapsed",
                            format_func=lambda i: ("⚡ " if rows[i].is_priority else "") + f"{i} · {rows[i].item} × {rows[i].qty}")
        row = rows[pick]
        names = cs.courier.tolist()

        def fmt(n):
            c, left = info.loc[n], int(info.loc[n, "cutoff_min"] - el)
            when = "already left" if left < 0 else f"pickup in {left} min"
            return f"{n} · ₹{c.cost_inr} · {c.speed} · {when}" + (" ★ suggested" if n == row.assigned_courier else "")

        courier = c2.selectbox("Courier", names, index=names.index(row.assigned_courier), format_func=fmt,
                               key=f"cour_{pick}", label_visibility="collapsed")
        left = info.loc[courier, "cutoff_min"] - el
        gone = left < 0
        if c3.button("Create label", type="primary", width="stretch", disabled=bool(gone)):
            create_label(world, pick, courier)
            notify(f"Label created for {pick} → {courier}", "🏷️")
            go()
        if gone:
            st.error(f"{courier} has already left - pick another courier.")
        elif left < SLA_BUFFER_MIN + PICKPACK_MIN:
            st.warning(f"{courier} leaves in {int(left)} min. The box must be staged {SLA_BUFFER_MIN} min before that - this order will probably miss it. Consider another courier.")
        st.caption(f"{row.channel} · ₹{info.loc[courier, 'cost_inr']} per parcel · {info.loc[courier, 'speed']}")

        n_bulk = min(10, len(new))
        b1, b2 = st.columns([2, 3])
        if b1.button(f"⚡ Label next {n_bulk} with suggested couriers", width="stretch"):
            for r in new.head(n_bulk).itertuples():
                create_label(world, r.order_id, r.assigned_courier)
            notify(f"{n_bulk} labels created (priority first)", "🏷️")
            go()
        b2.caption("For the quiet minutes: clears the top of the queue in one click, you can still change any courier later by re-booking.")


def import_panel():
    """XYZ lives in spreadsheets today: this lets the office paste in a spreadsheet export instead of retyping."""
    with st.expander("📤 Import new orders from a spreadsheet (CSV)"):
        st.caption("Columns: order_id, channel, sku, qty, priority (yes/no, optional). If any row is wrong, nothing is imported and every problem is listed.")
        sample = pd.DataFrame({"order_id": ["XY-9001", "XY-9002"], "channel": ["Amazon", "Shopify"],
                               "sku": world["products"].sku.iloc[:2], "qty": [1, 2], "priority": ["yes", "no"]})
        st.download_button("⬇ Download a sample file", sample.to_csv(index=False), "orders_template.csv", "text/csv")
        up = st.file_uploader("Choose a CSV file", type="csv", label_visibility="collapsed")
        if up is not None and st.button("Import orders", type="primary"):
            try:
                n, problems = import_orders(world, pd.read_csv(up))
            except Exception as e:  # unreadable file
                n, problems = 0, [f"Could not read the file: {e}"]
            if problems:
                st.error("Nothing was imported:\n\n" + "\n".join(f"- {p}" for p in problems[:10]))
            else:
                notify(f"{n} orders imported - they are in the office queue now", "📤")
                go()


def track_panel():
    with st.container(border=True):
        st.markdown('<div class="sec">🔎 Track any order</div><div class="sub">Type an order ID to see exactly where it is right now</div>', unsafe_allow_html=True)
        q = st.text_input("Order ID", placeholder="e.g. XY-1088", label_visibility="collapsed").strip().upper()
        if not q:
            return
        hit = orders[orders.order_id == q]
        if hit.empty:
            st.warning(f"No order found with ID {q}.")
            return
        r = hit.iloc[0]
        done = {"new": 1, "label_ready": 2, "staged": 4, "shipped": 5}[r.status]
        ev = world["events"].get(q, {})
        rng = np.random.default_rng(int(q[3:]))
        t, steps, demo_times = r.created_at, [], False
        for i, name in enumerate(["Order received", "Label created", "Picked & packed", "Staged for courier", "Shipped"]):
            if i:
                t = t + timedelta(minutes=int(rng.integers(6, 25)))
            if i >= done:
                steps.append((name, "in progress" if i == done else "-", "current" if i == done else "todo"))
            elif i in ev:  # a real action recorded by this app
                steps.append((name, ev[i].strftime("%H:%M"), "done"))
            else:          # history from before the demo started
                demo_times = True
                steps.append((name, min(t, datetime.now()).strftime("%H:%M") + " *", "done"))
        where = f" · box in slot **{r.slot}**" if r.status == "staged" and pd.notna(r.slot) else ""
        st.markdown(f"**{r['item']} × {r.qty}** · {r.channel} · {r.assigned_courier} · due **{due_text(r)}** · late risk **{r.risk * 100:.0f}%**{where}")
        st.markdown(ui.timeline(steps), unsafe_allow_html=True)
        if r.health == "late":
            st.markdown(ui.alert("bad", "This order is past its deadline - see the Courier pickup tab to re-book it."), unsafe_allow_html=True)
        if demo_times:
            st.caption("* Times marked with a star are demo history. Steps you do in this app are recorded with real times.")


def office_alerts():
    """Things the warehouse raised that the office must act on (stock reported missing, transfers in progress)."""
    missing = [i for i in world["issues"] if i["open"] and i["type"] == "Stock"]
    if missing:
        names = ", ".join(f"{i['order']}" for i in missing[:5])
        st.markdown(ui.alert("warn", f"🔔 Warehouse reported {len(missing)} item(s) missing: <b>{names}</b>. These orders are on hold - recount, then resolve the issue in the Issues tab."),
                    unsafe_allow_html=True)
    wt = int(orders.waiting_transfer.sum())
    if wt:
        st.markdown(ui.alert("warn", f"🚚 {wt} order(s) are Waiting for Transfer from Warehouse 2. Pickers skip them until the stock arrives."), unsafe_allow_html=True)


def capacity_panel():
    """The early warning: can the team finish every open order before each courier leaves?"""
    st.markdown('<div class="sec">⏱ Capacity check per courier pickup</div>'
                f'<div class="sub">Open orders × {PER_ORDER_MIN} min ÷ workers, against the time left before each ship-by deadline</div>', unsafe_allow_html=True)
    workers = int(st.number_input("Workers on shift", 1, 10, len(WORKERS), key="workers_on"))
    cap = capacity(orders, world, workers)
    for col, r in zip(st.columns(len(cap)), cap.itertuples()):
        when = r.pickup_at.strftime("%H:%M")
        if r.status == "left":
            kind, body = ("bad", f"Left at {when}<br><b>{r.open_n} open order(s) must be re-booked</b>"
                          + (f" - shift to {r.shift_to}" if r.shift_to else "")) if r.open_n else ("good", f"Left at {when}<br>Nothing pending")
        elif r.status == "gap":
            fix = []
            if pd.notna(r.workers_needed) and r.workers_needed <= workers + 3:
                fix.append(f"add a worker (needs {int(r.workers_needed)}, you have {workers})")
            if r.shift_to:
                fix.append(f"shift to {r.shift_to}")
            kind, body = "bad", (f"Pickup {when} · {r.mins_avail} min of work time<br>{r.open_n} open · team can do {r.can_do}<br>"
                                 f"<b>{r.gap}-order gap.</b> " + (("; or ".join(fix)[0].upper() + "; or ".join(fix)[1:] + ".") if fix else "No courier has room - tell the office."))
        else:
            kind = "warn" if r.status == "tight" else "good"
            body = f"Pickup {when} · {r.mins_avail} min of work time<br>{r.open_n} open · team can do {r.can_do}" + (" · <b>tight</b>" if r.status == "tight" else " · on track")
        col.markdown(ui.alert(kind, f"<b>{r.courier}</b><br>{body}"), unsafe_allow_html=True)


def office_board():
    k = kpis(orders)
    st.markdown(ui.kpi_row(k), unsafe_allow_html=True)
    office_alerts()
    capacity_panel()
    track_panel()
    import_panel()

    # ---- Needs attention now: the 6 most urgent open orders as cards ----
    open_o = orders[~orders.status.isin(DONE)]
    urgent = open_o.assign(_r=open_o.health.map({"late": 0, "at_risk": 1, "ok": 2})).sort_values(
        ["_r", "is_priority", "risk"], ascending=[True, False, False]).head(6)
    st.markdown('<div class="sec">🔥 Needs attention now</div><div class="sub">Most urgent open orders - act on these first</div>', unsafe_allow_html=True)
    st.markdown('<div class="cards">' + "".join(ui.order_card(r, due_text(r)) for _, r in urgent.iterrows()) + "</div>", unsafe_allow_html=True)

    office_queue()

    # ---- Two charts ----
    c1, c2 = st.columns(2)
    labels = list(ui.STATUS_LABEL.values())
    stages = orders.status.map(ui.STATUS_LABEL).value_counts().reindex(labels, fill_value=0).reset_index()
    stages.columns = ["Stage", "Orders"]
    f1 = px.bar(stages, x="Orders", y="Stage", orientation="h", text="Orders", title="Where are today's orders?",
                color="Stage", color_discrete_map={"Needs label": "#F59E0B", "Ready to pick": "#4F46E5", "Staged": "#7C3AED", "Shipped": "#22C55E"})
    f1.update_traces(textposition="outside", textfont_size=14, cliponaxis=False)
    f1.update_xaxes(range=[0, max(int(stages.Orders.max()), 1) * 1.18])
    f1.update_yaxes(autorange="reversed", title=None)
    pressure = open_o.groupby(["assigned_courier", "health"]).size().reset_index(name="Orders")
    pressure["health"] = pressure["health"].map({"late": "Late", "at_risk": "At risk", "ok": "On track"})
    f2 = px.bar(pressure, x="assigned_courier", y="Orders", color="health", title="Deadline pressure by courier",
                color_discrete_map={"Late": "#DC2626", "At risk": "#F59E0B", "On track": "#22C55E"},
                category_orders={"health": ["Late", "At risk", "On track"]})
    f2.update_xaxes(title=None)
    for f in (f1, f2):
        f.update_layout(height=290, margin=dict(l=10, r=10, t=45, b=10), paper_bgcolor="white", plot_bgcolor="white",
                        legend_title=None, showlegend=(f is f2), legend=dict(orientation="h", y=-0.2))
    c1.plotly_chart(f1, width="stretch")
    c2.plotly_chart(f2, width="stretch")

    st.markdown('<div class="sec">All open orders</div><div class="sub">Search and filter the full list</div>', unsafe_allow_html=True)
    f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
    search = f1.text_input("Search", placeholder="Order ID or item...")
    health = f2.multiselect("Show", ["late", "at_risk", "ok"], default=["late", "at_risk", "ok"],
                            format_func={"late": "Late", "at_risk": "At risk", "ok": "On track"}.get)
    only_pri = f3.toggle("Priority only")
    show_done = f4.toggle("Show completed")

    df = orders.copy()
    if not show_done:
        df = df[~df.status.isin(DONE)]
    df = df[df.health.isin(health + (["done"] if show_done else []))]
    if only_pri:
        df = df[df.is_priority]
    if search:
        s = search.lower()
        df = df[df.order_id.str.lower().str.contains(s) | df.item.str.lower().str.contains(s)]
    df = df.sort_values(["is_priority", "mins_left"], ascending=[False, True])  # priority first, then closest deadline

    view = df.assign(
        Health=df.health.map(FLAG),
        Order=df.apply(lambda r: ("⚡ " if r.is_priority else "") + r.order_id, axis=1),
        Due=df.apply(due_text, axis=1),
        Slot=df.slot.fillna(""),
        Reason=df.main_reason + df.stock_short.map({True: " · ⚠ low stock", False: ""}),
    )[["Health", "Order", "item", "qty", "channel", "status", "assigned_courier", "Slot", "Due", "risk", "Reason"]]
    view.columns = ["", "Order", "Item", "Qty", "Channel", "Status", "Courier", "Box slot", "Due", "Late risk", "Reason"]
    view["Status"] = view["Status"].map(ui.STATUS_LABEL)
    view["Late risk"] = view["Late risk"] * 100  # progress column shows the raw number, so scale to 0-100

    st.caption(f"{len(view)} orders shown · priority first, then closest deadline")
    st.dataframe(view, hide_index=True, width="stretch", height=380,
                 column_config={"Late risk": st.column_config.ProgressColumn(format="%d%%", min_value=0, max_value=100)})
    st.download_button("⬇ Export this list (CSV)", view.to_csv(index=False), "open_orders.csv", "text/csv")


# =====================================================================================
# WAREHOUSE
# =====================================================================================
def create_transfer(order_row):
    """Auto transfer task: the stock is in Warehouse 2, so the order waits for it and pickers carry on with other orders."""
    if not any(x["order"] == order_row["order_id"] and not x["done"] for x in world["transfers"]):
        world["transfers"].append({"order": order_row["order_id"], "n": int(min(order_row["second_stock"], max(10, order_row["shortfall"]))), "done": False})
        release_order(world, order_row["order_id"])


def pick_area(worker):
    ready = orders[orders.status == "label_ready"]
    if ready.empty:
        st.success(t("all_done"))
        return
    urgency = lambda d: d.sort_values(["is_priority", "mins_left"], ascending=[False, True])
    held = ready.waiting_transfer | ready.on_hold                    # not handed to pickers right now
    mine = urgency(ready[(ready.picker == worker) & ~held])
    free = urgency(ready[ready.picker.isna() & ~held])
    busy = ready[ready.picker.notna() & (ready.picker != worker)]

    st.markdown(f'<div class="sec">{t("pick_title", n=len(ready))}</div>'
                f'<div class="sub">{t("pick_sub", p=int(ready.is_priority.sum()), b=len(busy))}</div>', unsafe_allow_html=True)
    if len(busy):
        st.caption(t("in_progress") + " · ".join(f"{r.picker} → {r.order_id}" for r in busy.itertuples()))
    if int(held.sum()):
        st.caption(t("hold_note", n=int(held.sum())))
    prod = world["products"]
    conf = confusable(world)
    pairs = {tuple(sorted((a, b))) for a, bs in conf.items() for b in bs}
    if pairs:
        pi = prod.set_index("sku")
        st.caption(t("watch") + " · ".join(f"{pi.loc[a, 'name']} {pi.loc[a, 'variant']} ↔ {pi.loc[b, 'variant']}" for a, b in sorted(pairs)))

    # ---- No order in hand: one big button gives the most urgent order a picker can actually pick ----
    if mine.empty:
        if free.empty:
            st.info(t("all_taken"))
            return
        pickable = free[~free.cant_pick]
        if pickable.empty:
            st.markdown(ui.alert("warn", t("nothing_pickable")), unsafe_allow_html=True)
        first = (pickable if len(pickable) else free).iloc[0]
        if len(pickable):
            st.markdown(ui.alert("good", t("next_for_you", pri="⚡ " if first.is_priority else "", oid=first.order_id, item=first["item"], qty=first.qty)),
                        unsafe_allow_html=True)
        if st.button(t("start_next", oid=first.order_id), type="primary", width="stretch"):
            made = []
            for _, r in free.iterrows():
                if r["cant_pick"]:       # never hand a picker an order whose stock is not on the shelf
                    if r["second_stock"] >= r["qty"] - r["main_stock"]:
                        create_transfer(r)
                        made.append(r["order_id"])
                    continue
                claim_order(world, r["order_id"], worker)
                break
            if made:
                st.session_state.flash = t("auto_transfer", oid=", ".join(made))
            go()
        return

    row = mine.iloc[0]
    oid = row["order_id"]
    pm = prod["sku"] == row["sku"]
    main, second = int(prod.loc[pm, "main_stock"].iloc[0]), int(prod.loc[pm, "second_stock"].iloc[0])
    pick_key = f"pick_{oid}"
    chosen = st.session_state.get(pick_key)
    correct = chosen == row["variant"]
    step = 1 if row["cant_pick"] else (3 if correct else 2)

    st.markdown(ui.steps(step, [t("step1"), t("step2"), t("step3")]), unsafe_allow_html=True)
    st.markdown(ui.task_card(row, main, second, due_text(row), "p-late" if row["mins_left"] < 0 else "p-risk" if row["mins_left"] < AT_RISK_MIN else "p-ok",
                             (t("lbl_bin"), t("lbl_main"), t("lbl_wh2"))), unsafe_allow_html=True)
    if row["mins_left"] < 0:
        st.markdown(ui.alert("warn", t("late_warn", m=-row["mins_left"], c=row["assigned_courier"])), unsafe_allow_html=True)
    if row["stock_short"] and not row["cant_pick"]:
        st.markdown(ui.alert("warn", t("tight", main=main, r=int(row["reserved_ahead"]))), unsafe_allow_html=True)

    def put_back():
        if st.button(t("put_back"), key=f"back_{oid}", width="stretch"):
            release_order(world, oid)
            go()

    def not_found():
        """Item is not on the shelf: flag the stock, put the ORDER on hold as an Issue, alert the office, move the picker on."""
        if st.button(t("cant_find"), key=f"nf_{oid}", width="stretch"):
            log_issue(world, "Stock", oid, f"{row['item']} not found at {row['bin']} (system said {main}). Recount needed.", "Warehouse")
            prod.loc[pm, "main_stock"] = 0
            release_order(world, oid)
            st.session_state.flash = t("reported", oid=oid)
            go()

    # ---- Stock is not in the main warehouse (it changed after the order was handed out) ----
    if row["cant_pick"]:
        st.markdown(ui.alert("bad", t("no_stock", main=main, q=row["qty"])), unsafe_allow_html=True)
        if second >= int(row["qty"]) - main:
            if st.button(t("make_transfer"), type="primary", width="stretch"):
                create_transfer(row)
                st.session_state.flash = t("auto_transfer", oid=oid)
                go()
        else:
            st.info(t("not_in_wh2"))
        not_found()
        put_back()
        return

    # ---- Wrong product / variant: check the barcode PRINTED ON THE ITEM, so the app compares against what is ----
    # ---- really in the worker's hand, not what they believe. ----
    if not correct:
        family = prod[prod["name"] == row["name"]]
        others = family[family.sku.isin(conf.get(row["sku"], []))]
        if len(others):   # these two have been mixed up before: extra-loud warning
            st.markdown(ui.confusable_card(row["variant"], others["variant"].iloc[0], t("conf_title"), t("conf_hint")), unsafe_allow_html=True)

        def register(sku, variant):
            st.session_state[pick_key] = variant
            if variant not in (row["variant"], "?") and (oid, variant) not in world["logged"]:
                world["logged"].add((oid, variant))
                log_issue(world, "Wrong variant", oid, f"Near-miss: picked {variant} instead of {row['variant']}", "Warehouse")
                record_confusion(world, row["sku"], sku)   # the system learns which look-alikes get mixed up
            go()

        st.markdown(f'<div class="sec">{t("check_title")}</div><div class="sub">{t("check_sub")}</div>', unsafe_allow_html=True)
        with st.form(f"scan_{oid}", clear_on_submit=True):
            code = st.text_input("Item barcode", placeholder=t("placeholder"), label_visibility="collapsed")
            if st.form_submit_button(t("check_btn"), type="primary", width="stretch"):
                hit = lookup_barcode(prod, code)
                register(None, "?") if hit is None else register(hit["sku"], hit["variant"])
        if chosen == "?":
            st.markdown(ui.alert("warn", t("unknown_code")), unsafe_allow_html=True)
        elif chosen:
            st.markdown(ui.alert("bad", t("wrong", scanned=chosen, need=f"<u>{row['variant']}</u>")), unsafe_allow_html=True)
        with st.expander(t("no_scanner")):
            st.caption(t("no_scanner_cap"))
            for i, (col, fr) in enumerate(zip(st.columns(len(family)), family.itertuples())):
                if col.button(fr.variant, key=f"var_{oid}_{i}", width="stretch"):
                    register(fr.sku, fr.variant)
        with st.expander("🧪 Demo helper: barcodes printed on the look-alike items in this bin"):
            st.caption("In real life these are on the items. Shown here so you can try the scanner (type any of them).")
            st.markdown("  \n".join(f"{r.variant}: `{r.barcode}`" for r in family.itertuples()))
        not_found()
        put_back()
        return

    slot = next_slot(world["orders"], world["couriers"], row["assigned_courier"])
    st.markdown(ui.alert("good", t("correct", slot=slot, c=row["assigned_courier"])), unsafe_allow_html=True)
    a = st.checkbox(t("count_chk", q=row["qty"]), key=f"a_{oid}")
    b = st.checkbox(t("label_chk", oid=oid), key=f"b_{oid}")
    if a and b and st.button(t("packed_btn", slot=slot), type="primary", width="stretch"):
        done_slot = pack_order(world, oid)
        st.session_state.flash = t("flash_dup", oid=oid) if done_slot is None else t("flash_packed", oid=oid, slot=done_slot, c=row["assigned_courier"])
        go()


def transfer_area():
    """Open transfer tasks. Orders here are 'Waiting for Transfer'; the pickers carry on with other orders meanwhile."""
    open_t = [x for x in world["transfers"] if not x["done"]]
    if not open_t:
        return
    st.markdown(f'<div class="sec">{t("wt_title", n=len(open_t))}</div><div class="sub">{t("wt_sub")}</div>', unsafe_allow_html=True)
    for x in open_t:
        r = orders[orders.order_id == x["order"]]
        if r.empty:
            continue
        r = r.iloc[0]
        c1, c2 = st.columns([3, 2])
        c1.markdown(f"**{x['order']}** · {r['item']} · {x['n']} units")
        if c2.button(t("stock_arrived", oid=x["order"]), key=f"arr_{x['order']}", width="stretch"):
            move_stock(world, r["sku"], x["n"])
            x["done"] = True
            go()


def warehouse():
    if st.session_state.get("flash"):
        st.success(st.session_state.pop("flash"))
    c1, c2 = st.columns([3, 2])
    worker = c1.radio(t("who"), WORKERS, horizontal=True, key="worker")
    c2.radio("Language / भाषा", ["English", HINDI], horizontal=True, key="lang")
    pick_area(worker)
    transfer_area()


# =====================================================================================
# COURIER PICKUP
# =====================================================================================
def pickup():
    el, cs = elapsed(), world["couriers"]
    st.markdown('<div class="sec">🚚 Courier pickups</div><div class="sub">Staged boxes vs. orders still being prepared, per courier. Each box has a slot in its courier\'s lane.</div>', unsafe_allow_html=True)
    for _, c in cs.iterrows():
        cname, left = c.courier, c.cutoff_min - el
        mine = orders[orders.assigned_courier == cname]
        staged, waiting = mine[mine.status == "staged"], mine[mine.status.isin(["new", "label_ready"])]
        gone = left < 0
        exposed = pd.concat([waiting, staged]) if gone else waiting  # orders that will miss this courier
        tone, cls, txt = (("red", "p-late", "Already left") if gone else
                          (("amber", "p-risk", f"Pickup in {int(left)} min") if left < 60 else ("blue", "p-ok", f"Pickup in {int(left)} min")))
        at = (world["now"] + timedelta(minutes=int(c.cutoff_min))).strftime("%H:%M")
        chips = [f"{r.order_id} · {r.slot}" for r in staged.sort_values("slot").itertuples()]
        st.markdown(ui.courier_card(cname, f"₹{c.cost_inr} per parcel · {c.speed} · pickup at {at} · lane {c.lane}", txt, cls, tone,
                                    len(staged), len(waiting), chips), unsafe_allow_html=True)
        if len(exposed) and (gone or left < 30):
            what = "order(s) / box(es) were not collected" if gone else "order(s) will miss this pickup"
            st.markdown(ui.alert("bad" if gone else "warn", f"⚠ {len(exposed)} {what}. Re-book them on the next courier."), unsafe_allow_html=True)
            nxt = cs.assign(m=cs.cutoff_min - el).query("m > 30 and courier != @cname").sort_values("m").head(1)
            if len(nxt) and st.button(f"Re-book {len(exposed)} orders → {nxt.courier.iloc[0]}", key=f"rb_{cname}", type="primary", width="stretch"):
                rebook(world, exposed.order_id, nxt.courier.iloc[0])
                notify(f"{len(exposed)} orders re-booked to {nxt.courier.iloc[0]}", "🔁")
                go()
        if len(staged) and not gone:
            with st.expander(f"📋 Handover checklist · {cname} · {len(staged)} boxes"):
                st.caption(f"Count the boxes in lane {c.lane} together with the driver. Only tick a box if it is NOT there.")
                slots = staged.set_index("order_id")["slot"].to_dict()
                missing = st.multiselect("Boxes missing from the lane", staged.sort_values("slot").order_id.tolist(),
                                         format_func=lambda i: f"{i} (slot {slots[i]})", key=f"miss_{cname}")
                n_ok = len(staged) - len(missing)
                if st.button(f"Hand over {n_ok} boxes to {cname}", key=f"co_{cname}", type="primary", width="stretch", disabled=bool(n_ok == 0)):
                    shipped, lost = handover(world, cname, missing)
                    notify(f"{cname} collected {shipped} boxes" + (f" · {len(lost)} missing logged" if lost else ""), "🚚" if not lost else "⚠️")
                    go()
        st.write("")


# =====================================================================================
# RECEIVING, INVENTORY, ISSUES, INSIGHTS
# =====================================================================================
def receiving():
    prod, dl = world["products"], world["deliveries"]
    demand = orders[~orders.status.isin(DONE)].groupby("sku").qty.sum()
    short = {r.sku for r in prod.itertuples() if r.main_stock < demand.get(r.sku, 0)}
    arrived = [d for d in dl if d["status"] == "arrived"]
    units = sum(l["exp"] for d in arrived for l in d["lines"])
    fixes = sum(l["sku"] in short for d in arrived for l in d["lines"])
    st.markdown('<div class="sec">📥 Receiving</div><div class="sub">Unload → check against the delivery note → put on the shelves. Stock only becomes sellable after this.</div>', unsafe_allow_html=True)
    st.markdown(ui.kpi_row3([("Deliveries waiting", len(arrived), "arrived, not yet shelved", "amber"),
                             ("Units on the dock", units, "to be checked", "blue"),
                             ("Short SKUs fixed", fixes, "blocking orders today", "purple")]), unsafe_allow_html=True)
    for d in dl:
        u = sum(l["exp"] for l in d["lines"])
        fx = sum(l["sku"] in short for l in d["lines"])
        tone, cls, txt = {"arrived": ("amber", "p-risk", "Arrived - needs checking"), "expected": ("blue", "p-ok", "On the way"),
                          "received": ("blue", "p-ok", "Shelved ✔")}[d["status"]]
        st.markdown(ui.delivery_card(d, u, fx if d["status"] != "received" else 0, cls, tone, txt), unsafe_allow_html=True)
        if d["status"] != "arrived":
            continue
        with st.expander(f"Check & put away {d['id']}"):
            with st.form(f"form_{d['id']}"):
                vals = []
                for l in d["lines"]:
                    p = prod[prod.sku == l["sku"]].iloc[0]
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.markdown(f"**{p['name']} · {p['variant']}**  \nexpected **{l['exp']}** · shelf {p['bin']}" + ("  \n⭐ _orders are waiting for this_" if l["sku"] in short else ""))
                    rec = c2.number_input("Received", 0, 999, l["exp"], key=f"r_{d['id']}_{l['sku']}")
                    dam = c3.number_input("Damaged", 0, 999, 0, key=f"x_{d['id']}_{l['sku']}")
                    vals.append((l, p, int(rec), int(dam)))
                if st.form_submit_button("Put away on shelves", type="primary"):
                    for l, p, rec, dam in vals:
                        prod.loc[prod.sku == l["sku"], "main_stock"] += max(rec - dam, 0)
                        if rec != l["exp"] or dam:
                            log_issue(world, "Receiving", d["id"], f"{p['name']} {p['variant']}: expected {l['exp']}, received {rec}, damaged {dam}", "Warehouse")
                    d["status"] = "received"
                    notify(f"{d['id']} checked in and put on the shelves", "📥")
                    go()


def inventory():
    prod = world["products"].copy()
    open_o = orders[~orders.status.isin(DONE)]
    prod["demand"] = prod.sku.map(open_o.groupby("sku").qty.sum()).fillna(0).astype(int)
    prod["gap"] = prod.main_stock - prod.demand
    prod["Status"] = np.select([prod.main_stock == 0, prod.gap < 0, prod.gap < 3], ["🔴 Out", "🟠 Shortfall", "🟡 Low"], "🟢 OK")
    need = prod[(prod.gap < 0) & (prod.second_stock > 0)].copy()
    need["move"] = np.minimum(need.second_stock, -need.gap).astype(int)
    lost = prod[(prod.main_stock + prod.second_stock) < prod.demand]
    st.markdown('<div class="sec">🏬 Inventory & stock risk</div><div class="sub">Open orders vs. what is on the shelf - fix shortages BEFORE picking starts. '
                'Stock is reserved priority-first, so a product can be short even if every single order looks fine.</div>', unsafe_allow_html=True)
    st.markdown(ui.kpi_row3([("SKUs short in main", int((prod.gap < 0).sum()), "open orders need more than shelf stock", "amber"),
                             ("Units to transfer", int(need.move.sum()), "available in Warehouse 2", "blue"),
                             ("Short everywhere", len(lost), "must be reordered", "red")]), unsafe_allow_html=True)
    st.markdown('<div class="sec">Suggested transfers</div>', unsafe_allow_html=True)
    if need.empty:
        st.success("No transfers needed - main warehouse covers all open orders.")
    for _, r in need.sort_values("move", ascending=False).head(6).iterrows():
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"**{r['name']} · {r['variant']}** (bin {r['bin']}) - main has **{r.main_stock}**, open orders need **{r.demand}**. Warehouse 2 has {r.second_stock}.")
        if c2.button(f"Move {r.move} units", key=f"mv_{r.sku}", type="primary", width="stretch"):
            move_stock(world, r.sku, r.move)
            notify(f"Moved {r.move} units of {r['name']} {r['variant']} to the main warehouse", "📦")
            go()
    top = prod.sort_values("demand", ascending=False).head(12).assign(SKU=lambda d: d["name"] + " · " + d.variant)
    lg = top.melt(id_vars="SKU", value_vars=["main_stock", "demand"], var_name="Type", value_name="Units")
    lg["Type"] = lg.Type.map({"main_stock": "In main warehouse", "demand": "Needed by open orders"})
    st.plotly_chart(style(px.bar(lg, x="SKU", y="Units", color="Type", barmode="group", title="Shelf stock vs. open demand (top 12 SKUs)",
                                 color_discrete_map={"In main warehouse": "#4F46E5", "Needed by open orders": "#F59E0B"}), 340), width="stretch")
    t = prod[["name", "variant", "barcode", "bin", "main_stock", "second_stock", "demand", "Status"]]
    t.columns = ["Product", "Variant", "Barcode", "Bin", "Main", "Warehouse 2", "Open demand", "Status"]
    st.dataframe(t.sort_values("Status"), hide_index=True, width="stretch", height=300)


def issues():
    iss = world["issues"]
    n_open = sum(i["open"] for i in iss)
    st.markdown(f'<div class="sec">🗂 Issue log</div><div class="sub">{n_open} open · {len(iss) - n_open} resolved · every problem has an owner, nothing is forgotten</div>', unsafe_allow_html=True)
    with st.expander("➕ Report a problem"):
        with st.form("new_issue", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            t = c1.selectbox("Type", ["Stock", "Wrong variant", "Courier", "Receiving", "Damaged", "Other"])
            od = c2.text_input("Order ID (optional)")
            who = c3.selectbox("Owner", ["Office", "Warehouse", "Courier desk"])
            tx = st.text_input("What happened?")
            if st.form_submit_button("Add issue", type="primary") and tx:
                log_issue(world, t, od or "-", tx, who)
                go()
    show = st.radio("Show", ["Open", "Resolved", "All"], horizontal=True, label_visibility="collapsed")
    for x in iss:
        if (show == "Open" and not x["open"]) or (show == "Resolved" and x["open"]):
            continue
        st.markdown(ui.issue_card(x), unsafe_allow_html=True)
        if x["open"] and st.button("Mark resolved", key=f"res_{x['id']}"):
            x["open"] = False
            notify(f"Issue {x['order']} marked as resolved", "✅")
            go()


def success_panel():
    """The pitch in numbers: what XYZ would track to know Fulfillment Hub is working."""
    m = success_metrics(orders, world)
    st.markdown('<div class="sec">🎯 Success metrics</div><div class="sub">What XYZ would track, live from today\'s data</div>', unsafe_allow_html=True)
    tone = lambda bad: "red" if bad else "green"
    st.markdown('<div class="kpis" style="grid-template-columns:repeat(4,1fr)">' + "".join([
        ui.kpi("On-time ship rate", f"{m['on_time_rate'] * 100:.0f}%", "finished by the ship-by deadline", "green" if m["on_time_rate"] >= 0.9 else "amber"),
        ui.kpi("Wrong-item near-misses", m["near_misses"], "caught at the scan, before shipping", "green"),
        ui.kpi("Stock-out picks", m["stock_out_picks"], "open orders not pickable from the shelf", tone(m["stock_out_picks"])),
        ui.kpi("Missed pickups", m["missed_pickups"], "orders on a courier that already left", tone(m["missed_pickups"])),
    ]) + "</div>", unsafe_allow_html=True)


def delay_panel():
    """Where do delays come from? Which courier slips, and which step of the process holds orders back."""
    st.markdown('<div class="sec">🔎 Where delays come from</div><div class="sub">Which courier slips and which step holds orders back, live from today\'s data</div>', unsafe_allow_html=True)
    b = top_bottleneck(orders)
    if b["stage"]:
        st.warning(f"**Biggest bottleneck right now:** {b['text']}")
    else:
        st.success(b["text"])
    c1, c2 = st.columns(2)
    cp = courier_performance(orders, world)
    if not cp.empty:
        cp = cp.assign(rate=cp.on_time_rate * 100)
        fig = px.bar(cp, x="rate", y="courier", orientation="h", title="On-time rate by courier (%)",
                     hover_data={"orders": True, "late": True, "at_risk": True, "rate": ":.0f"},
                     color_discrete_sequence=["#16A34A"])
        fig.update_xaxes(range=[0, 100])
        c1.plotly_chart(style(fig), width="stretch")
    sb = stage_breakdown(orders).melt(id_vars="stage", value_vars=["ok", "at_risk", "late"], var_name="Health", value_name="Orders")
    sb["Health"] = sb["Health"].map({"ok": "On track", "at_risk": "At risk", "late": "Late"})
    fig2 = px.bar(sb, x="Orders", y="stage", color="Health", orientation="h", title="Open orders by process step",
                  color_discrete_map={"On track": "#16A34A", "At risk": "#F59E0B", "Late": "#DC2626"})
    fig2.update_yaxes(autorange="reversed", title=None)
    c2.plotly_chart(style(fig2), width="stretch")


def insights():
    success_panel()
    delay_panel()
    st.caption(f"Risk = work still to do (label {LABEL_MIN} min, pick & pack {PICKPACK_MIN} min, stock transfer {TRANSFER_MIN} min) compared with the time left before the courier deadline. "
               "It is a transparent rule on purpose: the team can check any score by hand. Handling times are assumptions you can tune in logic.py.")
    open_o = orders[~orders.status.isin(DONE)]
    hi = open_o[open_o.risk > 0.5]
    top = hi.main_reason.value_counts()
    st.info(f"**{len(hi)} open orders** have more than 50% risk of missing their courier." + (f" Biggest cause right now: **{top.index[0]}**." if len(top) else ""))
    c1, c2 = st.columns(2)
    why = open_o[open_o.risk >= 0.25].main_reason.value_counts().reset_index()
    why.columns = ["Reason", "Orders"]
    c1.plotly_chart(style(px.bar(why, x="Orders", y="Reason", orientation="h", title="Why orders are at risk (risk 25%+)", color_discrete_sequence=["#4F46E5"])), width="stretch")
    h = open_o.assign(Risk=open_o.risk * 100)
    c2.plotly_chart(style(px.histogram(h, x="Risk", nbins=20, title="Risk spread of open orders (%)", color_discrete_sequence=["#7C3AED"])), width="stretch")
    c3, c4 = st.columns(2)
    byp = (open_o.groupby("name").risk.mean() * 100).sort_values().reset_index()
    c3.plotly_chart(style(px.bar(byp, x="risk", y="name", orientation="h", title="Average risk by product (%)", color_discrete_sequence=["#F59E0B"])), width="stretch")
    if world["issues"]:
        it = pd.DataFrame(world["issues"]).groupby("type").size().reset_index(name="Count")
        c4.plotly_chart(style(px.bar(it, x="type", y="Count", title="Issues logged by type", color_discrete_sequence=["#DC2626"])), width="stretch")


def about():
    st.markdown("""
### What I chose to focus on, and why
The brief lists seven pains. I ranked them by one question: **what makes a customer's parcel late, wrong, or lost, and how often?**

1. **Orders that cannot be picked because stock is missing** (most important). It silently blocks an order *after* the team has already started work, and it hits priority orders hardest. The app checks stock *before* picking, reserves stock priority-first so two orders can't claim the same last unit, and turns a shortage into one tap (move from Warehouse 2, or "can't find it").
2. **Deadlines and priority.** Every order has a deadline (courier cut-off minus a {buf}-minute buffer). Priority always sorts first, and a risk score says *why* an order may miss its courier, so delays stop being a surprise.
3. **Boxes lost between packing and the courier.** Each packed box gets a named slot in its courier's lane, and handover is a checklist, so a missing box is logged at the dock instead of discovered by the customer.

Wrong variants are caught by checking the barcode printed on the item against the order (a phone or USB scanner works; typing the number works too), with tap-to-verify only as a no-scanner fallback. Status visibility, receiving and the issue log are included because they are small and support the three above.

### How this app maps to XYZ's problems
| XYZ problem | What the app does | Where |
|---|---|---|
| Hard to see an order's status | Live status board + **track any order** timeline with real step times | Office board |
| Delays go unnoticed | Live countdown to each deadline, late / at-risk flags, risk score with a reason | Office board, Insights |
| Priority orders get mixed in | Priority pinned first in every list, fastest courier suggested | Office board, Warehouse |
| Stock missing / not found | Stock reserved priority-first, checked **before** picking, one-tap transfer from Warehouse 2, "can't find it" report | Warehouse, Inventory |
| Wrong product / variant shipped | Worker scans the item's own barcode; a mismatch is blocked and logged as a near-miss. Look-alikes mixed up twice become **confusable** and get an extra-loud warning | Warehouse |
| Delays noticed too late | **Capacity check** per courier: open orders × 4 min ÷ workers vs. time left, with advice (add a worker or shift courier) | Office board |
| Boxes misplaced / courier missed | Staging slots, handover checklist, one-click re-booking (also for boxes left behind) | Courier pickup |
| Deliveries must be unloaded, checked, shelved | Count received vs. expected, flag damage, put away; mismatches are logged automatically | Receiving |
| Problems handled informally | Issue log with owner and status; the app logs problems automatically | Issues |

### Design choices
- **Warehouse team is not tech-savvy:** pick your name once, press one big "Start next order" button, then 3 clear steps. The app hands out orders, so two people never pick the same one.
- **One shared truth:** office and warehouse use the same data (SQLite), so a label made in the office shows up in the warehouse.
- **Bridge from spreadsheets:** the office can import a CSV instead of retyping orders.
- **Office sees urgency first:** the 6 most urgent orders are shown as cards before any table. Office picks the courier with cost, speed and pickup time side by side.
- **Stock is real:** packing an order takes its items off the shelf count, so inventory never drifts from the pick list.
- **Explainable risk:** a simple rule (work left vs. time left) instead of a model trained on made-up data, so anyone can check a score.

### Deliberately not built
Label printing, real courier/marketplace APIs, logins, and multi-item orders.

### Limits (honest)
All data is synthetic. Data is saved in a single SQLite file and shared by everyone using the app (last write wins - fine for a small team, a real rollout would use a proper database). Screens update when you click or press Refresh, not by themselves. One item per order. Handling times are assumptions, not measurements.
""".replace("{buf}", str(SLA_BUFFER_MIN)))


# =====================================================================================
# PAGE
# =====================================================================================
_el = elapsed()
_nxt = world["couriers"].assign(m=world["couriers"].cutoff_min - _el).query("m > 0").sort_values("m").head(1)
_pick = f"Next pickup: {_nxt.courier.iloc[0]} in {int(_nxt.m.iloc[0])} min" if len(_nxt) else "All couriers have left"
_k = kpis(orders)
st.markdown(ui.hero(_k["open"], _k["late"], _pick, datetime.now().strftime("%H:%M")), unsafe_allow_html=True)
st.markdown(ui.alert("good", "👋 <b>New here? 2-minute tour:</b> <b>Office board</b> (what is late, capacity check) → <b>Warehouse</b> (start an order, scan a wrong item on purpose, try हिन्दी) → <b>Courier pickup</b> (handover with a missing box) → <b>Insights</b> (success metrics). Open the sidebar for the step-by-step."), unsafe_allow_html=True)
_gone = set(world["couriers"][world["couriers"].cutoff_min < _el].courier)
_stuck = int((orders.status.isin(["new", "label_ready", "staged"]) & orders.assigned_courier.isin(_gone)).sum())
if _stuck:
    st.markdown(ui.alert("bad", f"⚠ {_stuck} order(s) are assigned to a courier that has already left. Open <b>Courier pickup</b> to re-book them."), unsafe_allow_html=True)
_n_new = int((orders.status == "new").sum())
_n_ready = int((orders.status == "label_ready").sum())
_n_dl = sum(d["status"] == "arrived" for d in world["deliveries"])
_n_iss = sum(i["open"] for i in world["issues"])
def stock_tab():
    """Inventory and receiving are one job for the warehouse lead: what is on the shelf, and what just arrived."""
    inv, rec = st.tabs(["🏬 Inventory & shortages", f"📥 Receiving ({_n_dl})"])
    with inv:
        inventory()
    with rec:
        receiving()


def insights_tab():
    insights()
    with st.expander("ℹ️ About this project: why these problems, how it maps to XYZ's pains", expanded=False):
        about()


tabs = st.tabs([f"📋 Office board ({_n_new})", f"🧺 Warehouse ({_n_ready})", "🚚 Courier pickup" + (" ⚠" if _stuck else ""),
                "📦 Stock", f"🗂 Issues ({_n_iss})", "📊 Insights & About"])
for _t, _f in zip(tabs, [office_board, warehouse, pickup, stock_tab, issues, insights_tab]):
    with _t:
        _f()
if "_toast" in st.session_state:
    _m, _i = st.session_state.pop("_toast")
    st.toast(_m, icon=_i)

with st.sidebar:
    st.markdown("### ⏱ Fulfillment Hub")
    st.caption("Deadline-driven fulfillment · demo for XYZ")
    st.markdown("**Try this demo flow**")
    st.markdown("1. **Office board** - see what is late and the **capacity check** (add workers and watch the gap close), label an order, import a CSV  \n"
                "2. **Warehouse** - pick a worker (try हिन्दी), start the next order, scan a *wrong* code, then the right one  \n"
                "3. **Courier pickup** - re-book orders from the courier that left, run a handover with a missing box  \n"
                "4. **Stock** - move stock before it blocks an order, check a delivery in  \n"
                "5. **Issues** - near-misses and missing boxes are logged automatically  \n"
                "6. **Insights & About** - why I chose these problems  \n\n"
                "**See it live:** open this app in a second browser window. Label an order in one, and it appears in the other's Warehouse tab after a click.")
    st.divider()
    st.caption("All data is synthetic. Data is shared between everyone using this app. Courier times are relative to when the demo started; countdowns run on the real clock.")
    if st.button("🔄 Refresh (see teammates' changes)", width="stretch"):
        st.rerun()
    if st.button("Reset demo for everyone", width="stretch"):
        store.reset(make_world)
        st.session_state.clear()
        st.rerun()

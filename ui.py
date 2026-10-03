"""ui.py - small HTML/CSS helpers so the app looks designed instead of default.
Streamlit shows raw tables by default; here we build cards, pills and a hero banner.
NOTE: the HTML strings have no indentation on purpose (indented lines turn into code blocks in Markdown).
"""
from html import escape

CSS = """<style>
[data-testid=stHeader]{background:transparent}
.block-container{padding-top:3.5rem;max-width:1250px}
footer,#MainMenu{visibility:hidden}
.hero{background:linear-gradient(135deg,#4F46E5 0%,#7C3AED 100%);color:#fff;border-radius:18px;padding:22px 28px;margin-bottom:18px}
.hero h1{margin:0;font-size:1.75rem;color:#fff;padding:0}
.hero p{margin:6px 0 0;opacity:.9;font-size:.95rem}
.hero .chips{margin-top:12px;display:flex;gap:8px;flex-wrap:wrap}
.hero .chip{background:rgba(255,255,255,.18);border-radius:99px;padding:4px 12px;font-size:.82rem}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}
.kpi{background:#fff;border-radius:14px;padding:14px 16px;border:1px solid #E5E7EB;border-left:5px solid var(--c)}
.kpi.green{--c:#16A34A}.kpi.red{--c:#DC2626}.kpi.amber{--c:#F59E0B}.kpi.blue{--c:#2563EB}.kpi.purple{--c:#7C3AED}.kpi.gray{--c:#6B7280}
.kl{font-size:.74rem;color:#6B7280;text-transform:uppercase;letter-spacing:.05em;font-weight:600}
.kv{font-size:2.1rem;font-weight:700;color:#111827;line-height:1.25}
.ks{font-size:.8rem;color:#6B7280}
.sec{font-size:1.15rem;font-weight:700;color:#111827;margin:8px 0 2px}
.sub{color:#6B7280;font-size:.88rem;margin-bottom:10px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-bottom:22px}
.oc{background:#fff;border:1px solid #E5E7EB;border-radius:14px;padding:14px 16px;border-top:4px solid var(--c)}
.oc.red{--c:#DC2626}.oc.amber{--c:#F59E0B}.oc.blue{--c:#4F46E5}
.oc .top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.oc .id{font-weight:700;color:#111827}
.oc .item{font-size:1.02rem;font-weight:600;margin:8px 0 2px;color:#111827}
.oc .meta{color:#6B7280;font-size:.83rem}
.bar{height:6px;background:#EEF0F4;border-radius:99px;margin:10px 0 5px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--c);border-radius:99px}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.74rem;font-weight:600;margin-right:4px}
.p-late{background:#FEE2E2;color:#B91C1C}.p-risk{background:#FEF3C7;color:#B45309}
.p-ok{background:#DCFCE7;color:#15803D}.p-pri{background:#E0E7FF;color:#4338CA}.p-stock{background:#F3E8FF;color:#7E22CE}
.task{background:#fff;border:1px solid #E5E7EB;border-radius:18px;padding:22px 26px;margin:10px 0 14px}
.task .name{font-size:2rem;font-weight:800;color:#111827;line-height:1.2}
.task .var{color:#4F46E5}
.binrow{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}
.bin{background:#EEF2FF;border-radius:12px;padding:10px 18px}
.bin .l{font-size:.7rem;color:#6B7280;text-transform:uppercase;letter-spacing:.05em;font-weight:600}
.bin .v{font-size:1.6rem;font-weight:800;color:#111827}
.steps{display:flex;gap:8px;margin:4px 0 6px}
.step{flex:1;padding:10px 14px;border-radius:12px;background:#EEF0F4;color:#6B7280;font-weight:600;font-size:.9rem}
.step.on{background:#4F46E5;color:#fff}.step.done{background:#DCFCE7;color:#15803D}
.al{border-radius:14px;padding:16px 18px;font-weight:700;font-size:1.05rem;margin:10px 0}
.al.bad{background:#FEE2E2;border:2px solid #DC2626;color:#7F1D1D;animation:shake .4s}
.al.good{background:#DCFCE7;border:2px solid #16A34A;color:#14532D}
.al.warn{background:#FEF3C7;border:2px solid #F59E0B;color:#78350F}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-8px)}75%{transform:translateX(8px)}}
[class*="st-key-var_"] button{min-height:4.2rem;font-size:1.15rem;font-weight:700;border-radius:14px}
.tl{display:flex;margin:14px 0 6px}
.tls{flex:1;text-align:center;position:relative}
.tls .dot{width:36px;height:36px;border-radius:50%;margin:0 auto 6px;display:flex;align-items:center;justify-content:center;font-weight:700;background:#E5E7EB;color:#6B7280}
.tls.done .dot{background:#16A34A;color:#fff}
.tls.current .dot{background:#4F46E5;color:#fff;box-shadow:0 0 0 5px #E0E7FF}
.tls:not(:last-child)::after{content:"";position:absolute;top:17px;left:calc(50% + 24px);width:calc(100% - 48px);height:3px;background:#E5E7EB}
.tls.done:not(:last-child)::after{background:#16A34A}
.tn{font-weight:600;font-size:.82rem;color:#111827}.tt{font-size:.75rem;color:#6B7280}
@media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}}
</style>"""

STATUS_LABEL = {"new": "Needs label", "label_ready": "Ready to pick", "staged": "Staged", "shipped": "Shipped"}
_TONE = {"late": ("red", "p-late"), "at_risk": ("amber", "p-risk"), "ok": ("blue", "p-ok"), "done": ("blue", "p-ok")}


def pill(text, cls):
    return f'<span class="pill {cls}">{escape(str(text))}</span>'


def hero(open_orders, late, next_pickup, clock=""):
    return (f'<div class="hero"><h1>⏱ Fulfillment Hub</h1>'
            f'<p>Deadline-driven fulfillment for XYZ · every order has a ship-by time, and everyone sees the same clock</p>'
            f'<div class="chips"><span class="chip">{open_orders} open orders</span>'
            f'<span class="chip">{late} late</span><span class="chip">{next_pickup}</span><span class="chip">🕒 Updated {clock}</span></div></div>')


def kpi(label, value, sub, tone):
    return f'<div class="kpi {tone}"><div class="kl">{label}</div><div class="kv">{value}</div><div class="ks">{sub}</div></div>'


def kpi_row(k):
    return '<div class="kpis">' + "".join([
        kpi("Late", k["late"], "past deadline", "red"),
        kpi("At risk", k["at_risk"], "under 30 min left", "amber"),
        kpi("Priority open", k["priority_open"], "must ship today", "blue"),
        kpi("Short on stock", k["blocked"], "stock will run out first", "purple"),
        kpi("Open orders", k["open"], "not yet shipped", "gray"),
    ]) + "</div>"


def order_card(r, due):
    tone, cls = _TONE[r.health]
    top = pill("⚡ Priority", "p-pri") if r.is_priority else ""
    stock = pill("⚠ Stock short", "p-stock") if r.stock_short else ""
    return (f'<div class="oc {tone}"><div class="top"><span class="id">{escape(r.order_id)}</span>'
            f'<span>{top}{pill(due, cls)}</span></div>'
            f'<div class="item">{escape(r["item"])} × {r.qty}</div>'
            f'<div class="meta">{escape(r.channel)} · {escape(r.assigned_courier)} · {STATUS_LABEL[r.status]}</div>'
            f'<div class="bar"><i style="width:{r.risk * 100:.0f}%"></i></div>'
            f'<div class="meta">Late risk <b>{r.risk * 100:.0f}%</b> · {escape(r.main_reason)} {stock}</div></div>')


def steps(active, names=None):
    names = names or ["1 · Locate item", "2 · Verify variant", "3 · Pack & stage"]
    cls = lambda i: "done" if i < active else ("on" if i == active else "")
    return '<div class="steps">' + "".join(f'<div class="step {cls(i + 1)}">{n}</div>' for i, n in enumerate(names)) + "</div>"


def task_card(row, main, second, due, due_cls, labels=("Go to bin", "Main stock", "Warehouse 2")):
    pri = pill("⚡ Priority", "p-pri") if row["is_priority"] else ""
    return (f'<div class="task"><div style="display:flex;justify-content:space-between;align-items:center">'
            f'<span class="meta">{escape(row["order_id"])} · {escape(row["channel"])} → {escape(row["assigned_courier"])}</span>'
            f'<span>{pri}{pill(due, due_cls)}</span></div>'
            f'<div class="name">{escape(row["name"])} — <span class="var">{escape(row["variant"])}</span> × {row["qty"]}</div>'
            f'<div class="binrow"><div class="bin"><div class="l">{escape(labels[0])}</div><div class="v">{escape(row["bin"])}</div></div>'
            f'<div class="bin"><div class="l">{escape(labels[1])}</div><div class="v">{main}</div></div>'
            f'<div class="bin"><div class="l">{escape(labels[2])}</div><div class="v">{second}</div></div></div></div>')


def confusable_card(need, other, title, hint):
    """Extra-loud warning for look-alike items that have been mixed up before."""
    box = "flex:1;border-radius:10px;padding:10px;text-align:center;font-size:1.3rem;font-weight:800;"
    return (f'<div style="border:3px solid #DC2626;background:#FEF2F2;border-radius:14px;padding:14px;margin:8px 0">'
            f'<div style="font-weight:800;color:#B91C1C;font-size:1.05rem">{escape(title)}</div>'
            f'<div style="display:flex;gap:10px;margin-top:10px"><div style="{box}background:#DCFCE7">✔ {escape(need)}</div>'
            f'<div style="{box}background:#FEE2E2">✖ {escape(other)}</div></div>'
            f'<div style="margin-top:8px">{escape(hint)}</div></div>')


def alert(kind, text):
    return f'<div class="al {kind}">{text}</div>'


_ISS = {"Stock": "p-stock", "Receiving": "p-stock", "Wrong variant": "p-late", "Courier": "p-risk", "Damaged": "p-late", "Other": "p-ok"}


def courier_card(name, meta, status, cls, tone, staged, waiting, ids):
    tot = staged + waiting
    pct = staged / tot * 100 if tot else 100
    chips = "".join(pill(i, "p-pri") for i in ids[:8]) + (pill(f"+{len(ids) - 8} more", "p-ok") if len(ids) > 8 else "")
    return (f'<div class="oc {tone}" style="margin-bottom:8px"><div class="top"><span class="id" style="font-size:1.1rem">{escape(name)}</span>'
            f'{pill(status, cls)}</div><div class="meta">{escape(meta)}</div>'
            f'<div class="bar"><i style="width:{pct:.0f}%"></i></div>'
            f'<div class="meta"><b>{staged}</b> boxes staged · <b>{waiting}</b> orders still being prepared</div>'
            f'<div style="margin-top:8px">{chips}</div></div>')


def issue_card(x):
    done = not x["open"]
    return (f'<div class="oc {"blue" if done else "amber"}" style="margin-bottom:6px;{"opacity:.55;" if done else ""}">'
            f'<div class="top"><span>{pill(x["type"], _ISS.get(x["type"], "p-ok"))}<span class="id">{escape(x["order"])}</span></span>'
            f'<span class="meta">{escape(x.get("time", ""))} · Owner: {escape(x["owner"])}</span></div>'
            f'<div class="item">{escape(x["text"])}</div>{pill("Resolved", "p-ok") if done else pill("Open", "p-risk")}</div>')


def timeline(steps):
    return '<div class="tl">' + "".join(
        f'<div class="tls {st}"><div class="dot">{"✓" if st == "done" else i + 1}</div>'
        f'<div class="tn">{escape(n)}</div><div class="tt">{escape(t)}</div></div>' for i, (n, t, st) in enumerate(steps)) + "</div>"


def kpi_row3(items):
    return '<div class="kpis" style="grid-template-columns:repeat(3,1fr)">' + "".join(kpi(*i) for i in items) + "</div>"


def delivery_card(d, units, fixes, cls, tone, txt):
    fx = pill(f"⭐ Fixes {fixes} short SKU(s)", "p-stock") if fixes else ""
    return (f'<div class="oc {tone}" style="margin-bottom:8px"><div class="top">'
            f'<span class="id" style="font-size:1.05rem">{escape(d["id"])} · {escape(d["supplier"])}</span>{pill(txt, cls)}</div>'
            f'<div class="meta">{len(d["lines"])} product lines · {units} units · {escape(d["eta"])}</div>'
            f'<div style="margin-top:8px">{fx}</div></div>')

"""data.py - builds all synthetic data for the Fulfillment Hub demo.

Everything is generated from a fixed random seed, so the demo looks the same every time.
Times are relative to "now" (the moment the app starts), so the demo always has orders
that are late, at risk, or fine - no matter when you open it.
"""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

CHANNELS = ["Amazon", "Flipkart", "Shopify"]
WORKERS = ["Asha", "Ravi", "Meena"]   # the 2-3 person warehouse team

# Couriers: cutoff_min = minutes after app start when the courier collects boxes.
# Morning Express has ALREADY left (-15) -> shows the "courier missed" problem.
# days = promised delivery time (used to pick a courier for priority orders).
# lane = the staging-area lane where this courier's boxes are kept.
COURIERS = pd.DataFrame(
    [
        ("Morning Express", -15, 90, "Same day", 0, "A"),
        ("Speedex Express", 40, 85, "Next day", 1, "B"),
        ("BlueRoute", 150, 60, "2 days", 2, "C"),
        ("IndiaPost Economy", 270, 38, "4-5 days", 5, "D"),
    ],
    columns=["courier", "cutoff_min", "cost_inr", "speed", "days", "lane"],
)

# 8 products x 3 variants. Similar-looking variants are what cause wrong shipments.
CATALOG = {
    "Cotton Tee": ["Black / S", "Black / M", "Black / L"],
    "Steel Bottle": ["500ml Blue", "750ml Blue", "750ml Black"],
    "Yoga Mat": ["4mm Green", "6mm Green", "6mm Grey"],
    "Desk Lamp": ["Warm", "Cool", "Neutral"],
    "Phone Case": ["iPhone 14", "iPhone 15", "Galaxy S23"],
    "Notebook": ["A5 Ruled", "A5 Plain", "A4 Ruled"],
    "Water Filter": ["Basic", "Plus", "Pro"],
    "Earbuds": ["White", "Black", "Blue"],
}


def make_products(rng):
    rows = []
    for i, (name, variants) in enumerate(CATALOG.items()):
        for j, variant in enumerate(variants):
            rows.append(
                {
                    "sku": f"{name[:3].upper()}-{i}{j}",
                    "name": name,
                    "variant": variant,
                    "bin": f"{chr(65 + i)}-{j + 1:02d}",  # e.g. A-01
                    "main_stock": int(rng.integers(3, 30)),
                    "second_stock": int(rng.integers(0, 45)),  # overflow warehouse
                }
            )
    df = pd.DataFrame(rows)
    # Every item carries a printed barcode. The warehouse screen checks the scanned code against the order.
    df["barcode"] = [f"8901234{i:05d}" for i in range(len(df))]
    # Force a few stock problems so the demo can show them
    df.loc[[2, 7, 13], "main_stock"] = [1, 0, 2]      # main warehouse nearly empty
    df.loc[[2, 13], "second_stock"] = [30, 25]        # ...but stock exists in warehouse 2
    df.loc[7, "second_stock"] = 0                     # truly out of stock
    return df


def make_orders(products, rng, now, n=250):
    # A few products sell much more than others (realistic), so use uneven weights
    w = rng.dirichlet(np.ones(len(products)) * 0.7)
    sku = rng.choice(products["sku"], size=n, p=w)
    age_min = rng.integers(5, 6 * 60, size=n)  # orders arrived over the last 6 hours
    is_priority = rng.random(n) < 0.15

    status, courier = [], []
    for a, pri in zip(age_min, is_priority):
        r = rng.random()
        shipped_p = min(a / 360 * 0.6, 0.6)  # older orders are more likely done
        if r < shipped_p:
            s = "shipped"
        elif r < shipped_p + 0.25:
            s = "staged"
        elif r < shipped_p + 0.40:
            s = "label_ready"
        else:
            s = "new"
        status.append(s)
        if s == "new":
            courier.append(None)
        elif pri:
            courier.append("Speedex Express")
        else:
            courier.append(rng.choice(COURIERS["courier"], p=[0.05, 0.2, 0.4, 0.35]))

    df = pd.DataFrame(
        {
            "order_id": [f"XY-{1001 + i}" for i in range(n)],
            "channel": rng.choice(CHANNELS, size=n, p=[0.5, 0.3, 0.2]),
            "sku": sku,
            "qty": rng.choice([1, 2, 3], size=n, p=[0.75, 0.2, 0.05]),
            "is_priority": is_priority,
            "status": status,
            "courier": courier,
            "created_at": [now - timedelta(minutes=int(a)) for a in age_min],
        }
    )
    df = df.sort_values("created_at").reset_index(drop=True)

    # Staged boxes get a time and a slot in their courier's lane (e.g. "B-03"),
    # so a misplaced box can be found by looking at one named place.
    lane = COURIERS.set_index("courier")["lane"]
    staged_at = [pd.NaT] * len(df)
    slot = [None] * len(df)
    counter = {}
    staged_idx = df.index[df.status == "staged"]
    for i in staged_idx:
        minutes_ago = int(rng.integers(2, 120))
        staged_at[i] = max(df.created_at[i] + timedelta(minutes=10), now - timedelta(minutes=minutes_ago))
    for i in sorted(staged_idx, key=lambda k: staged_at[k]):
        letter = lane[df.courier[i]]
        counter[letter] = counter.get(letter, 0) + 1
        slot[i] = f"{letter}-{counter[letter]:02d}"
    df["staged_at"] = pd.to_datetime(pd.Series(staged_at, index=df.index))
    df["slot"] = pd.Series(slot, index=df.index, dtype="object")
    df["picker"] = pd.Series([None] * len(df), index=df.index, dtype="object")  # which worker is picking it
    return df


def make_deliveries(products):
    sk = products.sku.tolist()
    return [
        {"id": "DL-201", "supplier": "FreshSupply Co", "status": "arrived", "eta": "arrived 09:40",
         "lines": [{"sku": sk[7], "exp": 20}, {"sku": sk[2], "exp": 15}, {"sku": sk[13], "exp": 12}]},
        {"id": "DL-202", "supplier": "PrimeGoods Ltd", "status": "arrived", "eta": "arrived 10:05",
         "lines": [{"sku": sk[4], "exp": 10}, {"sku": sk[10], "exp": 8}]},
        {"id": "DL-203", "supplier": "Metro Wholesale", "status": "expected", "eta": "due in about 45 min",
         "lines": [{"sku": sk[0], "exp": 25}, {"sku": sk[5], "exp": 18}]},
    ]


def make_issues():
    return [
        {"id": 3, "type": "Courier", "order": "XY-1088", "owner": "Office", "open": True, "time": "10:42",
         "text": "Morning Express left before this box was staged - needs re-booking"},
        {"id": 2, "type": "Stock", "order": "XY-1007", "owner": "Warehouse", "open": True, "time": "09:15",
         "text": "Yoga Mat 6mm Grey not found on shelf C-08 - recount needed"},
        {"id": 1, "type": "Wrong variant", "order": "XY-1031", "owner": "Warehouse", "open": False, "time": "08:50",
         "text": "Near-miss: reached for Black / L instead of Black / M - caught at verify step"},
    ]


def make_world(seed=7):
    """One call returns everything the app needs."""
    rng = np.random.default_rng(seed)
    now = datetime.now()
    products = make_products(rng)
    # History: Cotton Tee Black/M and Black/L were already mixed up twice (the near-miss in the issue log, and one more).
    # So the system already treats that pair as "confusable" and warns extra loudly. It learns more pairs as it goes.
    m, l = products.sku.iloc[1], products.sku.iloc[2]
    confusions = [[m, l], [l, m]]
    return {
        "now": now,                       # app start; courier cut-offs are relative to this
        "products": products,
        "couriers": COURIERS.copy(),
        "orders": make_orders(products, rng, now),
        "deliveries": make_deliveries(products),
        "issues": make_issues(),
        "transfers": [],                  # stock moves from Warehouse 2 that are on their way
        "logged": set(),                  # (order, variant) near-misses already logged
        "confusions": confusions,         # [expected sku, scanned sku] every time a look-alike was picked by mistake
        "events": {},                     # real timestamps for each order step, recorded as people act
    }


if __name__ == "__main__":  # quick self-check: python data.py
    w = make_world()
    print(w["orders"].status.value_counts().to_string(), "\n")
    print("priority orders:", int(w["orders"].is_priority.sum()))
    print(w["orders"][w["orders"].status == "staged"][["order_id", "courier", "slot", "staged_at"]].head())

# AI usage note (Fulfillment Hub)

## Which AI tool I used, and how

- **Claude** was my only AI tool. I wrote the plan first: the diagnosis (no single source of truth, no concept of time), which features to build deeply, simply or not at all, the workflow, the data model and the demo scenarios. Claude turned that plan into the working app (Python/Streamlit), synthetic data, automated tests and the README, over several versions. At the end I asked it to compare the three versions so I could pick one.
- **What I did myself:** problem framing and prioritization, using my plan as the acceptance test for each version, running the app and tests on my own machine, reading through `logic.py` (deadline, stock reservation, delay risk, capacity check) so I can explain how it works, setting up the repo, and deciding what goes into the public submission.

## Where I disagreed with, or changed, the AI

**1. Wrong variant: "tap to confirm" vs. checking the real item**

- *What the AI's earlier versions did:* a cheap tap-to-verify step, with barcode scanning listed as "not built".
- *What I did and why:* my plan ranked wrong-variant checks as a deep feature, because a wrong parcel costs a return, a refund and a rating. Tapping only records what the worker believes is in their hand, so a wrong item still gets through. I chose the version that compares the item's own barcode with the order, blocks a mismatch with a big red warning and logs it. Tap stays only as a fallback without a scanner. An unknown barcode is rejected but not counted as a mix-up, so the look-alike data stays clean (tested).

**2. Earlier versions contradicted my own diagnosis**

- *What I found:* my first root cause was "no single source of truth", yet two earlier versions kept data in the browser session, so each browser had its own copy and a refresh reset everything. They also listed Hindi/English with name-based login and confusable SKUs as "next steps", although my plan needed them for a team that is not comfortable with technology.
- *What I did:* I used the final version, where office and warehouse screens share one SQLite database, and Hindi, name login and confusable SKUs are built.

**3. Rules over a model.** Delay risk is a transparent formula (time left minus work left) and capacity is my plan's formula (open orders x 4 min / workers). With synthetic data a model would only learn my own random numbers, and every order shows a plain-English reason that the office can check by hand.

## How I checked the AI's work

- I ran the tests myself (`pytest -q`). The first run failed with an import error, which I fixed with a `pytest.ini`.
- I ran the app locally.
- I checked the README against the app and fixed a claim: it listed "analytics" as not built, but the app has an Insights tab with the four live success metrics.
- Later I asked for one more analyst-facing addition (courier on-time rate, orders by process step, biggest bottleneck). I kept it read-only and in `logic.py`, with tests, so it cannot change the workflow.

## Where the build differs from my plan

The README lists the gaps between the final build and my plan: Streamlit instead of React, a 20-minute buffer instead of 30, one shared screen for picking and packing, and one item per order.

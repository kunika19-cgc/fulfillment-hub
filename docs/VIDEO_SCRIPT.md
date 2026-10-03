# Video walkthrough script: Fulfillment Hub (target 4:30, hard limit 5:00)

Record your screen with the live app open. **Before recording:** press **Reset demo for everyone**, open a second, smaller browser window (the "warehouse"), and zoom to 110-125%.

## 0:00 - 0:45 · How I understood the problem
- "XYZ runs 200-300 orders a day on spreadsheets. A spreadsheet tells you *what exists*, but never *by when it must happen*."
- "Two root causes sit behind all seven pains: **no single source of truth**, and **no concept of time**. So I gave every order a **ship-by deadline** and built the whole app around that clock."
- "I went deep on three things: the deadline queue with priority, scan-to-verify, and stock handling. Staging and the issue log are simple. I left out real courier APIs, payments, logins and analytics on purpose."

## 0:45 - 1:50 · Office board (laptop)
- KPI strip and the red/amber cards: "I see what is late before I open any table."
- **Capacity check:** "Speedex leaves in about 19 minutes with 22 open orders. The team can do 14, so there is an 8-order gap, and it tells me to add a worker or shift to BlueRoute." Change **Workers on shift** and the gap closes. "This catches a delay *before* it happens."
- Create a label ("fastest courier that still fits for priority"). Mention CSV import in one sentence.

## 1:50 - 3:20 · Warehouse (phone/tablet), the main demo
- Switch to the second window, press Refresh: "A different browser, the same data. The label I just made is here."
- Pick a name, tap **Start next order**: "One big button, always the most urgent order. Two workers never get the same one." Tap **हिन्दी**: "The warehouse team can use Hindi."
- **Wrong variant (the wow moment):** scan a wrong barcode (use the demo helper). "Big red warning, in plain words, and it is logged." Point at the extra-loud **confusable** card or the watch-list: "Black/M and Black/L were mixed up twice, so the system now warns extra loudly. It learns new pairs as mistakes happen."
- Scan the right one, tick the two checks, **Packed**: "The box gets a slot in its courier's lane, and stock drops by exactly that amount."
- Stock: "If the item is only in Warehouse 2, a transfer task is created automatically, the order waits as *Waiting for Transfer*, and the picker moves on. If it is not on the shelf, the order goes on hold as an issue and the office gets an alert."

## 3:20 - 4:05 · Courier pickup and Issues
- "Morning Express already left: one click re-books everything stuck on it."
- Handover checklist: tick all but one box. "Expected 6, staged 5: the missing box is caught at the dock, not by the customer."
- Issues tab: "Everything the system caught is already here with an owner."

## 4:05 - 4:40 · Choices and limits
- "Risk is a transparent rule, not a model: the data is synthetic and the team can check a score by hand."
- Open **Insights**: "These are the four numbers XYZ would track: on-time ship rate, wrong-item near-misses caught, stock-out picks, missed pickups. They are live."
- Scroll to **Where delays come from**: "Which courier slips, which step holds orders back, and one line naming today's biggest bottleneck."
- "Honest limits: screens refresh on click, one SQLite file with last write wins, one item per order, and picker and packer share one screen. Those are my next steps, together with real courier APIs and scanner hardware."
- "55 automated tests cover the rules, the shared data, Hindi and the screen flows."

## Checklist before you press record
- [ ] Reset demo, second browser window ready, app running locally (streamlit run app.py)
- [ ] Rehearse once with a timer, stay under 5:00
- [ ] Say the success metrics in one breath if you have time: on-time ship rate, wrong-item rate, stock-out picks, missed pickups

# Assignment 4 — Design Spec

Date: 2026-11-10
App: `airplane_mode` (Frappe v15.125.0)

## Goals

Extend the Airplane Mode app to meet every requirement of the Frappe certification
Day 4 assignment: crew + gate tracking (Part 1), an Airport Shops module with rent
contracts, payments, receipts, reminders, settings and a web portal (Part 2), Shop
Types shipped via fixtures and a REST API demo with Bruno (Part 3).

## Decisions

- Receipt print format built with **Print Designer** (app to be installed on the bench).
- Payment schedule: **auto-generated on contract submit**, using **anniversary periods**
  counted from the contract start date (no `rent_due_day`).
- **Partial payments allowed**; overpayment of a period is blocked.
- Data model: **separate Tenant and Shop Contract** doctypes.
- Shop status is derived in **one place** (`sync_shop_status`), which also refreshes airport counts.
- Shop counts: stored on Airport for display; the report always computes them live.
- Reminders: one **upcoming** reminder (N days before due, up to the due date) and one
  **overdue** reminder (M days after due) per period — at most two emails per period.
- Concurrency: contract submit locks the shop row; payment submit/cancel lock the contract
  row then the period row (fixed order).
- Portal: `/shops` (list) and `/shops/<name>` (details) via `website_route_rules`.
- Money: every amount is rounded with `flt(value, precision)` (Currency precision) before
  it is stored or compared; no raw float equality.
- Locks use plain `SELECT … FOR UPDATE` only (no `SKIP LOCKED`), so nothing depends on a
  specific MariaDB feature beyond Frappe v15's own minimum.
- Sensitive shop fields (tenant/contract) are protected by **permlevel 1**, not by
  hiding them in API requests.

---

## Part 1 — Crew & Gate Numbers (module: Airplane Mode)

### Crew
- **Crew Member** (doctype): `full_name` (Data, reqd), `crew_role` (Select:
  Pilot / Co-Pilot / Cabin Crew / Flight Engineer), `email` (Data, Email), `phone` (Data, Phone).
  Naming: `CREW-.####`.
- **Flight Crew Member** (child table): `crew_member` (Link Crew Member, reqd),
  `crew_role` (Data, fetch_from `crew_member.crew_role`, read-only).
- **Airplane Flight**: new `crew` field (Table → Flight Crew Member), new section "Crew".
- `AirplaneFlight.validate` (Python, server-side — not JS):
  - throw if the same `crew_member` appears more than once in `crew`;
  - set each row's `crew_role` from `Crew Member.crew_role` via `frappe.db.get_value`
    (`fetch_from` is only a UI convenience and is not trusted).

### Gate Number
- **Airplane Flight**: `gate_number` (Data), `allow_on_submit = 1`.
- **Airplane Ticket**: `gate_number` (Data, read-only, `fetch_from: flight.gate_number`,
  `allow_on_submit = 1`).
- `AirplaneFlight.on_update` and `on_update_after_submit`: if
  `self.has_value_changed("gate_number")`, call
  `frappe.enqueue("airplane_mode.airplane_mode.tasks.update_ticket_gate_numbers",
  flight=self.name, queue="short", enqueue_after_commit=True)`.
  **No `job_id` / `deduplicate`.** In Frappe v15.125.0 `deduplicate=True` skips the new
  job when the existing one is `QUEUED` **or `STARTED`** (`utils/background_jobs.py`). If
  the gate changes again while a job is running and has already read the old gate, the
  new job would be dropped and tickets would keep the stale gate. Since the job is
  idempotent, an extra job is harmless; a dropped job is not.
  `enqueue_after_commit=True` makes sure the job only starts after the new gate is
  committed, so it always reads it.
  Frappe lifecycle: save → `on_update`; submit → `on_update` then `on_submit`; update after
  submit → `on_update_after_submit` only — so one change triggers one hook.
- `update_ticket_gate_numbers(flight)`: reads the **current** `gate_number` from the flight
  in the DB (not a job argument), then for every Airplane Ticket with `flight = <flight>`
  and `docstatus < 2` whose gate differs, `frappe.db.set_value(..., "gate_number", gate)`.
  The job is idempotent: running it twice, or after two quick gate changes, always leaves
  tickets on the latest gate. Uses `set_value` so submitted tickets are updated without
  re-running validation.

---

## Part 2 — Airport Shops Module

New Module Def **Airport Shops** (added to `modules.txt`, folder
`airplane_mode/airport_shops/`). All new doctypes below live in it.

### Doctypes

| Doctype | Type | Fields |
|---|---|---|
| Shop Type | normal | `shop_type_name` (Data, unique, autoname field), `enabled` (Check, default 1) |
| Airport Shop | normal | `shop_number` (Data, reqd), `shop_name` (Data, reqd), `airport` (Link Airport, reqd), `shop_type` (Link Shop Type), `area` (Float, sq ft), `status` (Select Available/Occupied, default Available, read-only), `current_tenant` (Link Tenant, read-only), `current_contract` (Link Shop Contract, read-only), `contract_expiry` (Date, read-only), `rent_amount` (Currency), `image` (Attach Image), `description` (Text Editor), `published` (Check, default 1) |
| Tenant | normal | `tenant_name` (Data, reqd), `email` (Data, Email, reqd), `phone` (Data, Phone), `company` (Data) |
| Shop Contract | submittable | `shop` (Link Airport Shop, reqd), `airport` (fetch), `tenant` (Link Tenant, reqd), `tenant_email` (fetch), `rent_amount` (Currency, monthly, default from shop), `start_date`, `end_date` (Date, reqd), `total_amount`, `total_paid`, `total_outstanding` (Currency, read-only), `rent_schedule` (Table Rent Schedule, read-only) |
| Rent Schedule | child | `period_start`, `period_end`, `due_date` (Date), `amount`, `paid_amount`, `outstanding_amount` (Currency), `status` (Select Unpaid/Partly Paid/Paid), `reminder_sent_on` (Date), `overdue_reminder_sent_on` (Date) |
| Rent Payment | submittable | `shop_contract` (Link Shop Contract, reqd), `shop`, `tenant`, `tenant_email` (fetched), `period_start` (Date, reqd — identifies the schedule row; JS pre-fills the earliest unpaid period), `period_outstanding` (Currency, read-only, before this payment, informational), `period_outstanding_after_payment` (Currency, read-only, snapshot written on submit), `amount` (Currency, reqd, > 0), `payment_date` (Date, default Today), `mode_of_payment` (Select Cash/Bank Transfer/Card/Cheque), `reference_no` (Data) |
| Shop Lead | normal | `lead_name` (Data, reqd), `email` (Data, Email, reqd), `phone` (Data), `shop` (Link Airport Shop), `message` (Small Text), `status` (Select New/Contacted/Converted/Lost) |
| Airport Shop Settings | Single | `default_rent_amount` (Currency), `enable_rent_reminders` (Check), `reminder_days_before` (Int, default 3, ≥ 0), `overdue_after_days` (Int, default 3, ≥ 1) |

Airport Shop `current_tenant`, `current_contract`, `contract_expiry` are **permlevel 1**
(read: Airport Authority Personnel, System Manager; nobody writes them through the form).

Naming: Airport Shop `{airport}-{shop_number}` (format autoname); Tenant `TEN-.####`;
Shop Contract `CON-.YYYY.-.####`; Rent Payment `RCPT-.YYYY.-.####`; Shop Lead `LEAD-.####`.

### Behaviour

**Default rent** — `AirportShop.before_insert`: if `rent_amount` empty, set it from
`Airport Shop Settings.default_rent_amount`. Shop Contract `rent_amount` fetches from shop
if empty.

**Airport Shop — protected fields**
- `PROTECTED = ("status", "current_tenant", "current_contract", "contract_expiry")`.
- `before_insert`: force `status = Available` and clear the other three, whatever was sent.
- `validate` (not new): if any protected field `has_value_changed`, `frappe.throw`. This
  blocks the form, REST API, imports and Server Scripts alike (they all go through
  `save()`). `sync_shop_status` writes with `frappe.db.set_value`, which skips `validate`,
  so it stays the only writer.
- `validate`: if `airport` changed and the shop has any submitted Shop Contract with
  `end_date >= today` (active or future), throw. Otherwise allowed.
- `on_update`: if `airport` changed, `update_airport_shop_counts` for both the previous
  (`get_doc_before_save().airport`) and the new airport.

**Rent schedule (anniversary periods)**
- `end_date` is the **last day** of the lease (inclusive).
- Period *n* starts at `get_anniversary_date(start_date, n)` and ends the day before
  period *n+1* starts, capped at `end_date`.
- `get_anniversary_date(start_date, months)` (in `airport_shops/utils.py`) =
  `frappe.utils.add_months(start_date, months)` (relativedelta). It is **always computed from
  the original `start_date`**, never chained from the previous period, so the day is clamped
  per month without drifting: 31 Jan → 28/29 Feb → 31 Mar → 30 Apr → 31 May.
- `due_date = period_start`. Full periods cost `rent_amount`.
- A final period shorter than a full month is **prorated by days**:
  `flt(rent_amount × days_in_period / days_in_full_period, precision)`,
  where the full period is `period_start` to `period_start + 1 month − 1 day`.
- Example: 15 Nov – 14 Feb → 3 full periods (15 Nov, 15 Dec, 15 Jan).
  15 Nov – 15 Feb → 3 full periods + a 1-day prorated period on 15 Feb.

**Shop Contract**
- `validate`: `end_date >= start_date`; `rent_amount > 0`; no other submitted contract on
  the same shop whose date range overlaps (inclusive dates).
- `before_submit`:
  1. Lock the shop: `SELECT name FROM \`tabAirport Shop\` WHERE name=%s FOR UPDATE`.
  2. **Re-run the overlap check** while holding the lock. A concurrent submit for the same
     shop waits on the lock, then sees the first contract (now submitted) and fails.
  3. Build `rent_schedule` (rules above), all rows Unpaid, `outstanding_amount = amount`;
     set contract totals.
- `on_submit` / `on_cancel`: call `sync_shop_status(self.shop)`.
- `before_cancel`: block if any submitted Rent Payment exists for this contract
  (cancel payments first).
- **Amend** (cancelled contract → new draft with `amended_from`):
  - Frappe's amend copies child rows, so `validate` on a doc with `amended_from` set (and
    `before_submit` for every contract) **clears `rent_schedule` and the totals and
    rebuilds them** from the contract's own dates and rent. Copied paid amounts, flags
    and email links are discarded.
  - Payments are never moved: they stay linked to the original (cancelled) contract,
    which can only have cancelled payments because of the `before_cancel` rule.
  - The overlap check excludes `docstatus = 2`, so the cancelled original doesn't block its
    amendment; the amendment is checked against every other submitted contract, and
    re-checked under the shop lock in `before_submit`.

**Shop status — single source of truth**
- `airplane_mode.airport_shops.utils.sync_shop_status(shop)`:
  find the submitted Shop Contract with `start_date <= today <= end_date` for that shop.
  If found → `status=Occupied`, `current_tenant`, `current_contract`, `contract_expiry=end_date`;
  else → `status=Available`, clear those three. Writes with `frappe.db.set_value` only when
  something changed, then calls `update_airport_shop_counts(airport)`.
- Every status change goes through this function — contract submit/cancel, the daily job,
  and Airport Shop `on_update`. Nothing else writes `status`.
- The state is **always recomputed from all submitted contracts for today**; it never
  frees a shop because "the old contract ended". So it handles:
  - future-dated contracts (activated by the daily job on their start date);
  - expired contracts (released the day after `end_date` if no other contract covers today);
  - **back-to-back contracts** (A ends 30 Nov, B starts 1 Dec): on 1 Dec the job finds B,
    so the shop stays Occupied and `current_contract` / `current_tenant` /
    `contract_expiry` switch to B, with no Available gap.
- The overlap rule guarantees at most one contract covers any day. "Today" is
  `frappe.utils.today()` (system time zone).

**Rent Payment (partial payments, concurrency-safe)**
- `validate`: contract is submitted; a schedule row with `period_start` exists;
  `amount > 0`; `amount <= outstanding_amount` (early, friendly check); fetch
  `period_outstanding` for display.
- Locking helper `_lock_period(contract, period_start)` — the **only** path used by both
  `on_submit` and `on_cancel`, called before any amount is read or written:
  1. `SELECT name FROM \`tabShop Contract\` WHERE name=%s AND docstatus=1 FOR UPDATE`
     (throw if not found).
  2. `SELECT name, amount, paid_amount FROM \`tabRent Schedule\` WHERE parent=%s
     AND parenttype='Shop Contract' AND period_start=%s FOR UPDATE` (throw if not found).
  Always contract row first, then period row, so two payments on different periods of the
  same contract cannot deadlock (both also update contract totals). This serialises all
  payments and cancellations for one contract.
  Frappe runs each request in one transaction (autocommit off) on InnoDB tables, so the
  locks hold until the request commits or rolls back.
- Precision: `p = frappe.get_precision("Rent Schedule", "amount")`. All sums, differences
  and comparisons use `flt(x, p)`; e.g. new outstanding = `flt(amount - new_paid, p)`,
  overpay check `flt(new_paid - amount, p) > 0`, Paid when `flt(outstanding, p) <= 0`.
- `on_submit`: `_lock_period` → `new_paid = flt(paid_amount + self.amount, p)`; throw if it
  exceeds `amount` (rolls back the whole submit) → write `paid_amount`,
  `outstanding_amount`, `status` (Paid when outstanding ≤ 0, Partly Paid when 0 < paid <
  amount) on the child row via `frappe.db.set_value` → `self.db_set(
  "period_outstanding_after_payment", outstanding)` (snapshot for the receipt; never
  recomputed later) → recompute contract `total_paid` / `total_outstanding` from the rows.
  A concurrent submit for the same contract waits on the lock, then sees the updated
  `paid_amount` and fails if it would overpay.
- `on_cancel`: `_lock_period` → subtract `self.amount` → recompute status and contract
  totals. Uses the same locks, so a cancel and a new payment can't interleave.
- Print format **Rent Receipt** built in Print Designer and exported with the app
  (print format JSON in module `Airport Shops`, `standard = Yes`). Shows tenant, shop,
  airport, period, amount paid, `period_outstanding_after_payment` (the stored snapshot, so
  reprinting an older receipt shows the balance as it was then), payment date, mode.

**Shop counts per airport**
- Airport gets read-only Int fields `total_shops`, `available_shops`, `occupied_shops`.
- `update_airport_shop_counts(airport)` recomputes via `frappe.db.count` and writes them;
  called by `sync_shop_status` and by Airport Shop `on_trash`, plus for the previous airport
  when a shop's airport changes.
- Script report **Airport Shop Occupancy** computes counts live with a GROUP BY query (never
  reads the stored fields): Airport, Total, Available, Occupied, Occupancy %; airport filter;
  bar chart.
- Workspace **Airport Shops** with shortcuts and number cards (Available / Occupied shops).

### Scheduler (`hooks.py`)
```python
scheduler_events = {
    "daily": [
        "airplane_mode.airport_shops.tasks.sync_all_shop_statuses",
        "airplane_mode.airport_shops.tasks.send_rent_reminders",
    ]
}
```
- `sync_all_shop_statuses()`: run `sync_shop_status` for every Airport Shop.
- `send_rent_reminders()`: return immediately if `enable_rent_reminders` is off. Only rows
  of submitted contracts with `status != Paid` are considered. Two independent passes:
  - **Upcoming** — `reminder_sent_on IS NULL` and
    `due_date - reminder_days_before <= today <= due_date`. Template
    `templates/emails/rent_reminder.html`. Sets `reminder_sent_on = today`.
  - **Overdue** — `overdue_reminder_sent_on IS NULL` and
    `today >= due_date + overdue_after_days`. Template
    `templates/emails/rent_overdue.html`. Sets `overdue_reminder_sent_on = today`.
  Each email shows shop, period, outstanding amount and due date. A period whose upcoming
  window was missed (e.g. scheduler down) gets no upcoming email — only the overdue one.
- Rent Schedule gets two more read-only fields: `reminder_email` and
  `overdue_reminder_email` (Link → Email Queue), so every flag points at the email it
  stands for.
- Per candidate row, inside its own **savepoint** (`frappe.db.savepoint(sp)`):
  1. `SELECT <flag>, status FROM \`tabRent Schedule\` WHERE name=%s FOR UPDATE` →
     re-check the flag is still NULL and status ≠ Paid; skip otherwise.
  2. `q = frappe.sendmail(recipients=[tenant_email], …, reference_doctype="Shop Contract",
     reference_name=contract)` (default `delayed=True`, no `now`, no `queue_separately`).
     In v15 this inserts the Email Queue row synchronously in the same transaction.
  3. If `q` is falsy (v15 returns `[]` when the recipient is filtered out, e.g.
     unsubscribed or empty email) → raise, so nothing is flagged.
  4. Set the flag to today and the link field to `q.name`.
  On any exception: `frappe.db.rollback(save_point=sp)` (undoes the lock-protected writes
  and the Email Queue insert for **that row only**), `frappe.log_error(...)`, continue
  with the next row.
  The scheduler commits once when the job ends. Result: a flag is never stored without
  its Email Queue row, and one bad row doesn't stop the others. An overlapping run waits on
  the row lock, then sees the flag set and skips. Plain `FOR UPDATE` works on any MariaDB
  that Frappe v15 supports.
- "Sent" means **queued**: actual delivery, and retries on SMTP failure, are Frappe's Email
  Queue's job (`status` Not Sent / Sent / Error, visible through the link field). We don't
  re-send on delivery errors.
- Flags never reset on a submitted contract: the schedule is built once on submit and is
  read-only, so due dates can't change (see Amend below).
- Settings form button **Send Reminders Now** → whitelisted method (System Manager /
  Airport Authority Personnel) that **enqueues** `send_rent_reminders` (no work or commits
  inside the web request) and shows "Reminders queued". The same dedupe rules apply.

---

## Web Portal

- Download `https://cdn.jsdelivr.net/npm/picnic` → `airplane_mode/public/css/picnic.min.css`.
- `airplane_mode/templates/shop_portal_base.html`: standalone `<!DOCTYPE html>` page,
  links `/assets/airplane_mode/css/picnic.min.css`, nav bar, `{% block content %}`.
  Does **not** extend `templates/web.html`.
- `www/shops/index.html` + `index.py`: lists published shops (card grid: name, number,
  airport, type, area, rent, status badge), optional `?airport=` filter. Each card links
  to `/shops/<name>`.
- `www/shops/shop.html` + `shop.py`: `website_route_rules = [{"from_route": "/shops/<shop>",
  "to_route": "shops/shop"}]`; reads `frappe.form_dict.shop`, 404 if missing/unpublished.
  Shows all details and an **"Interested? Apply to rent"** button (shown when Available)
  linking to `/shop-lead/new?shop=<name>`.
- Web Form **Shop Lead** (route `shop-lead`, guests allowed, fields lead_name, email,
  phone, shop, message). The `shop` field is pre-filled from the query string.
- Pages set `no_cache = 1`.

---

## Part 3

### Shop Types
- `hooks.py` fixtures add `{"dt": "Shop Type", "filters": [["name", "in", ["Stall",
  "Walk-through", "Normal"]]]}`; `fixtures/shop_type.json` contains the three, enabled.
- `airport_shop.js`: `frm.set_query("shop_type", () => ({ filters: { enabled: 1 } }))`.

### REST API (Bruno)
- Collection committed at `bruno/airplane_mode/`:
  - `List Shops (all fields).bru` — `GET {{base_url}}/api/resource/Airport Shop?fields=["*"]&limit_page_length=0`
    (the assignment asks for "all fields"; what comes back is limited by the user's permissions).
  - `List Shops (public fields).bru` — same with
    `fields=["name","shop_name","shop_number","airport","shop_type","area","rent_amount","status"]`.
  - `Create Shop.bru` — `POST {{base_url}}/api/resource/Airport Shop` with JSON body.
  - Header `Authorization: token {{api_key}}:{{api_secret}}`.
- `environments/local.bru` with `base_url`; key/secret as secret env vars (not committed).
- Auth: generate API key/secret from User → Settings → API Access for a dedicated API user.
- Permission demo: run the all-fields request once as an Airport Authority Personnel user
  (tenant/contract fields present) and once as a low-privilege user with read-only access
  to Airport Shop at permlevel 0 (those fields absent). A POST that tries to set `status` or
  `current_tenant` is ignored/rejected (forced on insert by `before_insert`).

---

## Roles & Permissions
- Airport Authority Personnel: full access to all Airport Shops doctypes and settings,
  plus read at permlevel 1 on Airport Shop.
- System Manager: full access (incl. permlevel 1 read).
- Travel Agent (existing role): read-only Airport Shop at permlevel 0 — used to show the
  API permission demo.
- Shop Lead: Guest create via web form only.

## Testing
Unit tests (`bench --site <site> run-tests --app airplane_mode`):
- `get_anniversary_date`: 31 Jan 2027 → 28 Feb, 31 Mar, 30 Apr (no drift);
  31 Jan 2028 (leap) → 29 Feb; 30 Jan → 28 Feb → 30 Mar; 29 Feb 2028 + 12 → 28 Feb 2029.
- Schedule: 15 Nov–14 Feb → 3 rows; 15 Nov–15 Feb → 4 rows with last prorated;
  31 Jan start → period starts 31 Jan, 28 Feb, 31 Mar; totals equal sum of rows.
- Overlapping contract rejected; non-overlapping adjacent contract allowed; overlap
  re-checked in `before_submit` (two drafts for the same dates: second submit fails).
- `sync_shop_status`: active contract → Occupied; future contract → stays Available, then
  Occupied once today reaches start (use `frappe.utils` time freezing / `freeze_time`);
  expired → Available; cancel → Available. Airport counts match after each.
- Partial payments: 40% + 60% → Partly Paid then Paid; third payment rejected (overpay);
  cancel one → back to Partly Paid; contract totals correct.
- Contract cancel blocked while payments exist.
- `update_ticket_gate_numbers` updates draft and submitted tickets; running it twice is a
  no-op; it uses the flight's current gate. Changing the gate on a submitted flight enqueues
  exactly one job; saving without a gate change enqueues none (patch `frappe.enqueue` and
  count calls). Two gate changes in a row (A → B → C) enqueue two jobs and tickets end on C
  whichever job runs last.
- Crew: duplicate crew member rejected server-side; tampered `crew_role` is overwritten
  from Crew Member.
- Airport Shop: changing `status`/`current_tenant`/`current_contract`/`contract_expiry`
  via `save()` throws; insert with `status=Occupied` is stored as Available; airport change
  blocked with an active/future contract; allowed otherwise and both airports' counts update.
- Permissions: `frappe.get_list("Airport Shop", fields=["*"])` as a Travel Agent user does not
  return `current_tenant`.
- Receipt snapshot: after 40% then 60%, the first payment still has
  `period_outstanding_after_payment` = 60% of rent.
- Precision: rent 1000 over a 31-day full period with a 10-day stub → 322.58; three
  payments of 333.33/333.33/333.34 on a 1000 period → Paid, outstanding 0.
- Payment on a missing period / cancelled contract rejected by `_lock_period`.
- `send_rent_reminders`: nothing when disabled; upcoming sent once inside the window and not
  before it or after the due date; overdue sent once after `overdue_after_days`; second run
  sends nothing; Paid rows skipped. Every flagged row links to an existing Email Queue row.
- Reminder failures: patch `frappe.sendmail` to raise for one row → that row has no flag
  and no Email Queue row, other rows are flagged with their queue rows, and an Error Log is
  created. Patch it to return `[]` → no flag.
- Amend: cancel a contract (no payments) → amend → submit: new schedule rebuilt with all
  rows Unpaid and empty flags; the original keeps its own rows; the amendment overlapping a
  different submitted contract is rejected.
- Back-to-back contracts: A (… → 30 Nov) and B (1 Dec → …) on one shop; with today frozen
  at 30 Nov → Occupied by A; at 1 Dec → still Occupied, `current_contract` = B,
  `current_tenant` = B's tenant; airport counts unchanged.

Manual: portal pages render with Picnic styling, lead web form pre-fills shop,
Print Designer receipt prints, Bruno requests succeed, two browser tabs submitting payments
for the same period cannot overpay.

## Setup Prerequisites
- MariaDB **10.6+** with InnoDB (Frappe v15 minimum; this bench runs 10.11.13). Only plain
  `SELECT … FOR UPDATE` is used.
- `bench get-app print_designer` (version compatible with Frappe v15) and
  `bench --site <site> install-app print_designer`.
- Scheduler enabled on the site (`bench --site <site> enable-scheduler`) and a worker running
  for the background job.

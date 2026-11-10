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
- Reminders: sent N days before each period's due date, **at most once per period**.
- Portal: `/shops` (list) and `/shops/<name>` (details) via `website_route_rules`.

---

## Part 1 — Crew & Gate Numbers (module: Airplane Mode)

### Crew
- **Crew Member** (doctype): `full_name` (Data, reqd), `crew_role` (Select:
  Pilot / Co-Pilot / Cabin Crew / Flight Engineer), `email` (Data, Email), `phone` (Data, Phone).
  Naming: `CREW-.####`.
- **Flight Crew Member** (child table): `crew_member` (Link Crew Member, reqd),
  `crew_role` (Data, fetch_from `crew_member.crew_role`, read-only).
- **Airplane Flight**: new `crew` field (Table → Flight Crew Member), new section "Crew".
  Validation: the same crew member may not appear twice on one flight.

### Gate Number
- **Airplane Flight**: `gate_number` (Data), `allow_on_submit = 1`.
- **Airplane Ticket**: `gate_number` (Data, read-only, `fetch_from: flight.gate_number`,
  `allow_on_submit = 1`).
- `AirplaneFlight.on_update` and `on_update_after_submit`: if
  `self.has_value_changed("gate_number")`, call
  `frappe.enqueue("airplane_mode.airplane_mode.tasks.update_ticket_gate_numbers",
  flight=self.name, gate_number=self.gate_number, queue="short", enqueue_after_commit=True)`.
- `update_ticket_gate_numbers(flight, gate_number)`: for every Airplane Ticket with
  `flight = <flight>` and `docstatus < 2`, `frappe.db.set_value(..., "gate_number", gate_number)`.
  Uses `set_value` so submitted tickets are updated without re-running validation.

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
| Rent Schedule | child | `period_start`, `period_end`, `due_date` (Date), `amount`, `paid_amount`, `outstanding_amount` (Currency), `status` (Select Unpaid/Partly Paid/Paid), `reminder_sent_on` (Date) |
| Rent Payment | submittable | `shop_contract` (Link Shop Contract, reqd), `shop`, `tenant`, `tenant_email` (fetched), `period_start` (Date, reqd — identifies the schedule row; JS pre-fills the earliest unpaid period), `period_outstanding` (Currency, read-only, informational), `amount` (Currency, reqd, > 0), `payment_date` (Date, default Today), `mode_of_payment` (Select Cash/Bank Transfer/Card/Cheque), `reference_no` (Data) |
| Shop Lead | normal | `lead_name` (Data, reqd), `email` (Data, Email, reqd), `phone` (Data), `shop` (Link Airport Shop), `message` (Small Text), `status` (Select New/Contacted/Converted/Lost) |
| Airport Shop Settings | Single | `default_rent_amount` (Currency), `enable_rent_reminders` (Check), `reminder_days_before` (Int, default 3, ≥ 0) |

Naming: Airport Shop `{airport}-{shop_number}` (format autoname); Tenant `TEN-.####`;
Shop Contract `CON-.YYYY.-.####`; Rent Payment `RCPT-.YYYY.-.####`; Shop Lead `LEAD-.####`.

### Behaviour

**Default rent** — `AirportShop.before_insert`: if `rent_amount` empty, set it from
`Airport Shop Settings.default_rent_amount`. Shop Contract `rent_amount` fetches from shop
if empty.

**Rent schedule (anniversary periods)**
- `end_date` is the **last day** of the lease (inclusive).
- Period *n* starts at `start_date + n months` (day clamped to month length, e.g. Jan 31 →
  Feb 28) and ends the day before period *n+1* starts, capped at `end_date`.
- `due_date = period_start`. Full periods cost `rent_amount`.
- A final period shorter than a full month is **prorated by days**:
  `rent_amount × days_in_period / days_in_full_period` (rounded to currency precision),
  where the full period is `period_start` to `period_start + 1 month − 1 day`.
- Example: 15 Nov – 14 Feb → 3 full periods (15 Nov, 15 Dec, 15 Jan).
  15 Nov – 15 Feb → 3 full periods + a 1-day prorated period on 15 Feb.

**Shop Contract**
- `validate`: `end_date >= start_date`; `rent_amount > 0`; no other submitted contract on
  the same shop whose date range overlaps (inclusive dates).
- `before_submit`: build `rent_schedule` (rules above), all rows Unpaid,
  `outstanding_amount = amount`; set contract totals.
- `on_submit` / `on_cancel`: call `sync_shop_status(self.shop)`.
- `before_cancel`: block if any submitted Rent Payment exists for this contract
  (cancel payments first).

**Shop status — single source of truth**
- `airplane_mode.airport_shops.utils.sync_shop_status(shop)`:
  find the submitted Shop Contract with `start_date <= today <= end_date` for that shop.
  If found → `status=Occupied`, `current_tenant`, `current_contract`, `contract_expiry=end_date`;
  else → `status=Available`, clear those three. Writes with `frappe.db.set_value` only when
  something changed, then calls `update_airport_shop_counts(airport)`.
- Every status change goes through this function — contract submit/cancel, the daily job,
  and Airport Shop `on_update`. Nothing else writes `status`.
- This covers future-dated contracts (activated by the daily job on their start date) and
  expired contracts (released the day after `end_date`).

**Rent Payment (partial payments, concurrency-safe)**
- `validate`: contract is submitted; a schedule row with `period_start` exists;
  `amount > 0`; `amount <= outstanding_amount` (early, friendly check); fetch
  `period_outstanding` for display.
- `on_submit`: inside the submit transaction:
  1. Lock the schedule row: `SELECT name, amount, paid_amount FROM \`tabRent Schedule\`
     WHERE parent=%s AND period_start=%s FOR UPDATE`.
  2. Re-check `paid_amount + self.amount <= amount`; otherwise `frappe.throw` (rolls back).
  3. Set `paid_amount`, `outstanding_amount`, `status` (Paid when outstanding = 0, Partly Paid
     when 0 < paid < amount), via `frappe.db.set_value` on the child row.
  4. Recompute contract `total_paid` / `total_outstanding`.
  A second concurrent submit for the same period blocks on the row lock until the first
  commits, then sees the updated `paid_amount` and fails if it would overpay.
- `on_cancel`: same lock, subtract `self.amount`, recompute status and contract totals.
- Print format **Rent Receipt** built in Print Designer and exported with the app
  (print format JSON in module `Airport Shops`, `standard = Yes`). Shows tenant, shop,
  airport, period, amount paid, period outstanding after this payment, payment date, mode.

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
- `send_rent_reminders()`: return immediately if `enable_rent_reminders` is off. Otherwise,
  for every Rent Schedule row of a submitted contract where `status != Paid`,
  `reminder_sent_on IS NULL` and `due_date - reminder_days_before <= today`:
  `frappe.sendmail` to the tenant (template `templates/emails/rent_reminder.html`: shop,
  period, outstanding amount, due date), then set `reminder_sent_on = today` on that row.
  Rows are claimed with `FOR UPDATE SKIP LOCKED` so overlapping runs cannot double-send;
  a retry or a second manual run sends nothing for rows already reminded.
- Settings form button **Send Reminders Now** → whitelisted method (System Manager /
  Airport Authority Personnel) calling `send_rent_reminders()` — same dedupe rules apply.

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
  - `List Shops.bru` — `GET {{base_url}}/api/resource/Airport Shop?fields=["*"]&limit_page_length=0`
  - `Create Shop.bru` — `POST {{base_url}}/api/resource/Airport Shop` with JSON body.
  - Header `Authorization: token {{api_key}}:{{api_secret}}`.
- `environments/local.bru` with `base_url`; key/secret as secret env vars (not committed).
- Auth: generate API key/secret from User → Settings → API Access.

---

## Roles & Permissions
- Airport Authority Personnel: full access to all Airport Shops doctypes and settings.
- System Manager: full access.
- Shop Lead: Guest create via web form only.

## Testing
Unit tests (`bench --site <site> run-tests --app airplane_mode`):
- Schedule: 15 Nov–14 Feb → 3 rows; 15 Nov–15 Feb → 4 rows with last prorated;
  31 Jan start → 28/29 Feb period start; totals equal sum of rows.
- Overlapping contract rejected; non-overlapping adjacent contract allowed.
- `sync_shop_status`: active contract → Occupied; future contract → stays Available, then
  Occupied once today reaches start (use `frappe.utils` time freezing / `freeze_time`);
  expired → Available; cancel → Available. Airport counts match after each.
- Partial payments: 40% + 60% → Partly Paid then Paid; third payment rejected (overpay);
  cancel one → back to Partly Paid; contract totals correct.
- Contract cancel blocked while payments exist.
- `update_ticket_gate_numbers` updates draft and submitted tickets.
- `send_rent_reminders`: nothing when disabled; sends once when enabled and due; second run
  sends nothing (`reminder_sent_on` set); Paid rows skipped.

Manual: portal pages render with Picnic styling, lead web form pre-fills shop,
Print Designer receipt prints, Bruno requests succeed, two browser tabs submitting payments
for the same period cannot overpay.

## Setup Prerequisites
- `bench get-app print_designer` (version compatible with Frappe v15) and
  `bench --site <site> install-app print_designer`.
- Scheduler enabled on the site (`bench --site <site> enable-scheduler`) and a worker running
  for the background job.

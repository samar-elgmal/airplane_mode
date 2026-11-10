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
- Payment schedule: **auto-generated monthly dues** on contract submit.
- Data model: **separate Tenant and Shop Contract** doctypes.
- Shop counts: **stored count fields on Airport** + a script report.
- Portal: `/shops` (list) and `/shops/<name>` (details) via `website_route_rules`.

---

## Part 1 — Crew & Gate Numbers (module: Airplane Mode)

### Crew
- **Crew Member** (doctype): `full_name` (Data, reqd), `crew_role` (Select:
  Pilot / Co-Pilot / Cabin Crew / Flight Engineer), `email` (Data, Email), `phone` (Data, Phone).
  Naming: autoname by `full_name` is avoided (duplicates); use `CREW-.####`.
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
  flight=self.name, gate_number=self.gate_number, queue="short")`.
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
| Airport Shop | normal | `shop_number` (Data, reqd), `shop_name` (Data, reqd), `airport` (Link Airport, reqd), `shop_type` (Link Shop Type), `area` (Float, sq ft), `status` (Select Available/Occupied, default Available, read-only), `current_tenant` (Link Tenant, read-only), `rent_amount` (Currency), `contract_expiry` (Date, read-only), `image` (Attach Image), `description` (Text Editor), `published` (Check, default 1) |
| Tenant | normal | `tenant_name` (Data, reqd), `email` (Data, Email, reqd), `phone` (Data, Phone), `company` (Data) |
| Shop Contract | submittable | `shop` (Link Airport Shop, reqd), `airport` (fetch), `tenant` (Link Tenant, reqd), `tenant_email` (fetch), `rent_amount` (Currency, default from shop), `start_date`, `end_date` (Date, reqd), `rent_due_day` (Int, default 1), `rent_schedule` (Table Rent Schedule, read-only) |
| Rent Schedule | child | `month` (Data, e.g. "2026-12"), `due_date` (Date), `amount` (Currency), `status` (Select Unpaid/Paid), `rent_payment` (Link Rent Payment) |
| Rent Payment | submittable | `shop_contract` (Link Shop Contract, reqd), `shop`, `tenant`, `tenant_email` (fetched), `month` (Data, "YYYY-MM"; JS pre-fills the earliest unpaid month of the chosen contract; validated server-side), `amount` (Currency), `payment_date` (Date, default Today), `mode_of_payment` (Select Cash/Bank Transfer/Card/Cheque), `reference_no` (Data) |
| Shop Lead | normal | `lead_name` (Data, reqd), `email` (Data, Email, reqd), `phone` (Data), `shop` (Link Airport Shop), `message` (Small Text), `status` (Select New/Contacted/Converted/Lost) |
| Airport Shop Settings | Single | `default_rent_amount` (Currency), `enable_rent_reminders` (Check), `reminder_day` (Int 1–28, default 1) |

Naming: Airport Shop `{airport}-{shop_number}` (format autoname); Tenant `TEN-.####`;
Shop Contract `CON-.YYYY.-.####`; Rent Payment `RCPT-.YYYY.-.####`; Shop Lead `LEAD-.####`.

### Behaviour

**Default rent** — `AirportShop.before_insert`: if `rent_amount` empty, set it from
`Airport Shop Settings.default_rent_amount`. Shop Contract `rent_amount` fetches from shop
if empty.

**Shop Contract**
- `validate`: `end_date > start_date`; no other submitted contract on the same shop whose
  date range overlaps.
- `before_submit`: build `rent_schedule` — one row per calendar month from `start_date`
  to `end_date`, `due_date` = that month's `rent_due_day` (clamped to month length),
  `amount = rent_amount`, `status = Unpaid`.
- `on_submit`: if contract is active today (start ≤ today ≤ end), set shop `status=Occupied`,
  `current_tenant`, `contract_expiry`.
- `on_cancel`: free the shop (Available, clear tenant/expiry) if this contract is the one on it.
  Block cancel if any schedule row is Paid (cancel payments first).

**Rent Payment**
- `validate`: contract must be submitted; `month` must match an Unpaid schedule row;
  `amount` defaults to that row's amount.
- `on_submit`: set the row `status=Paid`, `rent_payment=self.name` (via `db_set` on child row).
- `on_cancel`: revert row to Unpaid, clear link.
- Print format **Rent Receipt** built in Print Designer and exported with the app
  (print format JSON in module `Airport Shops`, `standard = Yes`).

**Shop counts per airport**
- Airport gets read-only Int fields `total_shops`, `available_shops`, `occupied_shops`.
- Helper `update_airport_shop_counts(airport)` recomputes via `frappe.db.count`; called from
  Airport Shop `on_update`/`on_trash` (and for the old airport if airport changed).
- Script report **Airport Shop Occupancy**: columns Airport, Total, Available, Occupied,
  Occupancy %; filter by airport; bar chart.
- Workspace **Airport Shops** with shortcuts and number cards (Available / Occupied shops).

### Scheduler (`hooks.py`)
```python
scheduler_events = {
    "daily": [
        "airplane_mode.airport_shops.tasks.send_rent_reminders",
        "airplane_mode.airport_shops.tasks.release_expired_shops",
    ]
}
```
- `send_rent_reminders(force=False)`: return if `enable_rent_reminders` is off; unless
  `force`, return unless `today.day == reminder_day`. For each Unpaid Rent Schedule row of a
  submitted contract with `due_date` in the current month, `frappe.sendmail` to the tenant
  (template `templates/emails/rent_reminder.html`: shop, month, amount, due date).
- `release_expired_shops()`: shops whose `contract_expiry < today` → Available, tenant cleared.
- Settings form button **Send Reminders Now** → whitelisted method calls
  `send_rent_reminders(force=True)` (System Manager only) — for the demo.

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
- Rent schedule generation (month count, due-day clamping e.g. 31 → Feb 28).
- Overlapping contract rejected.
- Contract submit → shop Occupied; cancel → Available.
- Rent Payment submit → row Paid; cancel → Unpaid.
- `update_ticket_gate_numbers` updates draft and submitted tickets.
- `send_rent_reminders` sends nothing when disabled; queues email when enabled + force.
- Airport counts update on shop insert/status change.

Manual: portal pages render with Picnic styling, lead web form pre-fills shop,
Print Designer receipt prints, Bruno requests succeed.

## Setup Prerequisites
- `bench get-app print_designer` (version compatible with Frappe v15) and
  `bench --site <site> install-app print_designer`.
- Scheduler enabled on the site (`bench --site <site> enable-scheduler`) and a worker running
  for the background job.

# Assignment 4: scenarios, examples and where they live

Every case the app handles: an example, what happens, the file that implements it, and the test that proves it.

**Path short forms** (relative to the repo root):
- `AM/` = `airplane_mode/airplane_mode/` (Airplane Mode module)
- `AS/` = `airplane_mode/airport_shops/` (Airport Shops module)
- `T:` = test name inside the test file shown

Run any test file: `bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.<file>` (for Part 1: `airplane_mode.airplane_mode.tests.test_crew_and_gate`).

---

## Part 1 – Crew and gate numbers

### 1.1 Crew members on a flight
Code: `AM/doctype/airplane_flight/airplane_flight.py` (`validate_crew`). Doctypes: `AM/doctype/crew_member/`, `AM/doctype/flight_crew_member/`. Tests: `AM/tests/test_crew_and_gate.py`.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 1 | Add crew | Flight gets "Ahmed – Pilot" and "Mona – Cabin Crew" | Saved; role shown next to each name | `test_crew_role_comes_from_crew_member` |
| 2 | Same person twice | Ahmed added in row 1 and row 2 | Error: "Row 2: … is already on this flight's crew." | `test_duplicate_crew_member_is_rejected` |
| 3 | Wrong role sent | Row says "Cabin Crew" but Ahmed is a Pilot in Crew Member | Saved as **Pilot**; the server copies the role from Crew Member | `test_crew_role_comes_from_crew_member` |

### 1.2 Gate number and the background job
Code: `AM/doctype/airplane_flight/airplane_flight.py` (`enqueue_gate_update`), `AM/tasks.py` (`update_ticket_gate_numbers`). Fields: `airplane_flight.json`, `airplane_ticket.json`.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 4 | New ticket | Flight gate A1, then book a ticket | Ticket gate = A1 | `test_new_ticket_gets_flight_gate` |
| 5 | Gate changes on a submitted flight | A1 → D4, click Update | Exactly one background job queued (after commit) | `test_gate_change_after_submit_enqueues_exactly_one_job` |
| 6 | Gate changes on a draft flight | A1 → B2, Save | One job queued | `test_gate_change_on_draft_flight_enqueues_one_job` |
| 7 | Save without changing the gate | Edit time only | No job | `test_save_without_gate_change_enqueues_nothing` |
| 8 | Job updates tickets | 1 draft and 1 submitted ticket, gate → B7 | Both tickets show B7 | `test_job_updates_draft_and_submitted_tickets` |
| 9 | Cancelled ticket | Cancelled ticket on the flight, gate → B7 | Cancelled ticket keeps A1 | `test_cancelled_ticket_is_skipped` |
| 10 | Job runs twice | Run the job again after it finished | Changes 0 tickets the second time | `test_job_reads_current_gate_and_is_idempotent` |
| 11 | Two quick changes | A1 → B2 → C3 | Two jobs; tickets end on **C3** whichever runs last | `test_two_gate_saves_enqueue_two_jobs_and_end_on_latest` |
| 12 | Job path is real | – | The queued path resolves to the real function | `test_job_path_resolves_to_real_function` |

---

## Part 2 – Airport Shops module

### 2.1 Shops
Code: `AS/doctype/airport_shop/airport_shop.py`, `airport_shop.js`. Tests: `AS/tests/test_airport_shop.py`.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 13 | Shop name | Airport code CAI, shop number A12 | Shop is named **CAI-A12** (URL `/shops/CAI-A12`) | `test_name_uses_airport_code` |
| 14 | Duplicate number, same airport | Second "B1" at CAI | Error: "Shop number B1 already exists at airport …" | `test_duplicate_number_in_same_airport_rejected` |
| 15 | Two airports share a code | Both coded CAI, both get A12 | Clear error instead of a database crash | `test_same_airport_code_collision_is_friendly` |
| 16 | Default rent | Settings default 750, shop saved with rent 0 | Rent becomes 750 | `test_default_rent_from_settings` |
| 17 | Client tries to set status | API insert with status "Occupied" and a tenant | Stored as **Available**, no tenant | `test_insert_forces_available_and_clears_tenant` |
| 18 | Status edited by hand | Change status on the form and save | Error: "… set automatically from shop contracts …" | `test_protected_fields_cannot_be_changed_by_save` |
| 19 | Expiry edited by hand | Change Contract Expiry | Same error | `test_changing_contract_expiry_through_save_is_rejected` |
| 20 | Normal save | Edit shop name only | Saves fine | `test_saving_unchanged_protected_fields_is_allowed` |
| 21 | Shop number after save | Try to edit shop number | Field is locked (`set_only_once`) | `airport_shop.json` |
| 22 | Move shop to another airport | No active contract | Allowed; both airports' counts update | `test_airport_change_updates_both_airports` |
| 23 | Move shop with a contract | Future or active contract exists | Error: "… airport cannot be changed." | `test_shop_contract.py` → `test_airport_change_blocked_with_active_or_future_contract` |
| 24 | Shop type list | "Stall" disabled | Stall missing from the Shop Type dropdown | `airport_shop.js` (`set_query`) |

### 2.2 Rent schedule (how the payment schedule works)
Code: `AS/utils.py` (`get_anniversary_date`, `build_rent_schedule`). Tests: `AS/tests/test_rent_schedule.py`.

| # | Scenario | Example (rent 1000) | Result | Test |
|---|---|---|---|---|
| 25 | Exact months | 15 Nov 2026 – 14 Feb 2027 | 3 periods: 15 Nov, 15 Dec, 15 Jan; 1000 each | `test_exact_three_months` |
| 26 | Short last period | 15 Nov 2026 – 15 Feb 2027 | 4 periods; last is 1 day = **35.71** (1000 × 1/28) | `test_short_last_period_is_prorated_by_days` |
| 27 | Start on the 31st | 31 Jan 2027 start | 31 Jan → 28 Feb → **31 Mar** (no drift to 28 Mar) | `test_month_end_does_not_drift`, `test_31st_start_uses_anniversaries` |
| 28 | Leap year | 31 Jan 2028 + 1 month | 29 Feb 2028 | `test_leap_year_february` |
| 29 | 29 Feb + 12 months | 29 Feb 2028 | 28 Feb 2029 | `test_leap_day_plus_twelve_months` |
| 30 | Day 30 start | 30 Jan 2027 | 30 Jan → 28 Feb → 30 Mar | `test_day_30` |
| 31 | Proration rounding | 1 Dec 2026 – 10 Jan 2027 | Second period **322.58** (1000 × 10/31) | `test_precision_of_prorated_amount` |
| 32 | Under one month | 1–10 Dec 2026 | One period of 322.58 | `test_contract_shorter_than_a_month` |
| 33 | Due dates | Any contract | Each period is due on its start date; all start Unpaid | `test_rows_start_unpaid_and_due_on_period_start` |

### 2.3 Contracts and shop status
Code: `AS/doctype/shop_contract/shop_contract.py`, `AS/utils.py` (`sync_shop_status`, `get_active_contract`, `update_airport_shop_counts`). Tests: `AS/tests/test_shop_contract.py`.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 34 | Submit a contract | 15 Nov – 15 Feb, rent 1000 | Schedule of 4 rows; totals = sum of rows | `test_submit_builds_schedule_and_totals` |
| 35 | End before start | Start 10 Jan, end 1 Jan | Error | `test_end_before_start_rejected` |
| 36 | Zero rent | Shop rent 0, contract rent 0 | Error: "Monthly Rent must be greater than zero." | `test_zero_rent_rejected` |
| 37 | Overlap | Jan–Mar exists; new one 31 Mar – Jun | Error: "… already has contract … for these dates." | `test_overlap_rejected_and_adjacent_allowed` |
| 38 | Adjacent | Jan–31 Mar exists; new one 1 Apr – Jun | Allowed | `test_overlap_rejected_and_adjacent_allowed` |
| 39 | Two drafts, same dates | Submit the first, then the second | Second submit refused (re-checked under a lock) | `test_overlap_rechecked_on_submit`, `test_before_submit_rechecks_overlap_with_locking_read` |
| 40 | Active contract | Started 10 days ago | Shop **Occupied**, tenant/contract/expiry filled; airport occupied count 1 | `test_active_contract_occupies_shop_and_updates_counts` |
| 41 | Future contract | Starts in 5 days | Shop stays Available; daily job makes it Occupied on the start date | `test_future_contract_activates_on_its_start_date` |
| 42 | Contract ended | Day after end date | Daily job sets shop Available | `test_expired_contract_releases_shop` |
| 43 | Back-to-back | A ends 30 Nov, B starts 1 Dec | On 1 Dec: still Occupied, switched to B's tenant, no gap | `test_back_to_back_contracts_switch_without_gap` |
| 44 | Cancel contract | Cancel the active one | Shop becomes Available | `test_cancel_releases_shop` |
| 45 | Cancel with payments | Contract has paid rent | Error: "Cancel the submitted Rent Payments … first." | `test_cancel_blocked_while_payments_exist` |
| 46 | Amend | Cancel, Amend, Submit | Fresh schedule, all Unpaid, no reminder flags; original keeps its rows | `test_amend_rebuilds_schedule` |
| 47 | Amend into an overlap | Amended dates overlap another contract | Error | `test_amend_overlapping_another_contract_rejected` |
| 48 | Current contract edited by hand | Change it on the shop | Error | `test_changing_current_contract_through_save_is_rejected` |
| 49 | Shop form after sync | Saving a shop changes its status | Form reloads, so the next save doesn't fail | `test_shop_reloaded_after_sync_writes` |

### 2.4 Rent payments and receipt
Code: `AS/doctype/rent_payment/rent_payment.py`, `rent_payment.js`; totals in `AS/utils.py` (`update_contract_totals`). Tests: `AS/tests/test_rent_payment.py`. Example below: period of 1000.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 50 | Partial then full | Pay 400, then 600 | Partly Paid (600 left) → Paid; contract totals updated | `test_partial_then_full` |
| 51 | Receipt balance | Print the 400 receipt after the 600 one | Shows "Outstanding After Payment" **600** (snapshot) | `test_partial_then_full` |
| 52 | Overpay | Period already paid, pay 1 more | Error | `test_overpayment_rejected` |
| 53 | Two payments at once | Draft for 600 made, someone else pays 600 first | Draft submit refused | `test_draft_that_became_an_overpayment_cannot_be_submitted` |
| 54 | Cancel one of two | Cancel the 600 | Back to Partly Paid, 400 paid | `test_cancel_reverts_period_and_totals` |
| 55 | Cancel a full payment | Cancel the single 1000 payment | Period Unpaid, paid 0 | `test_cancel_full_payment_returns_period_to_unpaid` |
| 56 | Thirds | 333.33 + 333.33 + 333.34 | Paid, outstanding exactly 0 | `test_precision_three_thirds_settle_exactly` |
| 57 | Rounding | API sends 400.004 | Stored as 400.00 | `test_amount_rounded_to_schedule_precision` |
| 58 | Zero amount | 0 | Error | `test_zero_amount_rejected` |
| 59 | Wrong period | Period start 20 Nov (no such period) | Error | `test_unknown_period_rejected` |
| 60 | Cancelled contract | Pay against a cancelled contract | Error | `test_cancelled_contract_rejected` |
| 61 | Details filled in | Choose the contract | Shop, tenant, email and outstanding filled | `test_fetches_contract_details` |
| 62 | Next unpaid period | First period paid | Form suggests the next period and its outstanding | `test_open_periods_in_order` |
| 63 | No access | Travel Agent asks for open periods | Permission error | `test_open_periods_needs_contract_read_permission` |

Receipt print format "receipt" (Print Designer): `airplane_mode/print_designer_formats/airplane_mode/receipt.json`, shipped via `pd_standard_format_folder` in `hooks.py`.

### 2.5 Shop counts per airport
Code: `AS/utils.py` (`update_airport_shop_counts`), fields on `AM/doctype/airport/airport.json`, report `AS/report/airport_shop_occupancy/`, cards `AS/number_card/*`, workspace `AS/workspace/airport_shops/`.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 64 | Add / delete shops | 2 shops, delete 1 | Airport shows Total 2 → 1 | `test_airport_shop.py` → `test_airport_counts_follow_insert_and_delete` |
| 65 | Report | 2 shops, 1 occupied | Report: total 2, available 1, occupied 1, 50 %; bar chart | `test_occupancy_report.py` → `test_counts_are_computed_live` |
| 66 | Report ignores stored numbers | Airport field wrongly says 99 | Report still says 2 (counts live) | `test_counts_are_computed_live` |
| 67 | Number cards | Workspace | "Available Shops" and "Occupied Shops" counts | `AS/number_card/` |

### 2.6 Settings and rent reminders
Code: `AS/doctype/airport_shop_settings/`, `AS/tasks.py` (`send_rent_reminders`, `_send_one`, `sync_all_shop_statuses`), templates `airplane_mode/templates/emails/rent_reminder.html`, `rent_overdue.html`, scheduler in `airplane_mode/hooks.py`. Tests: `AS/tests/test_settings.py`, `AS/tests/test_reminders.py`. Example below: days before = 3, overdue after = 3, period due **1 Mar 2027**.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 68 | Bad settings | Days before −1, or overdue after 0 | Error | `test_negative_days_before_rejected`, `test_overdue_days_must_be_positive` |
| 69 | Send Reminders Now | Click the button | Job queued after commit (no work inside the click) | `test_send_now_enqueues_reminder_job_after_commit` |
| 70 | Reminders off | Toggle off | Nothing sent | `test_disabled_sends_nothing` |
| 71 | Too early | 25 Feb (4 days before) | No email | `test_upcoming_only_inside_window` |
| 72 | Inside the window | 26 Feb | "Rent due" email queued; row flagged and linked to the Email Queue row | `test_upcoming_only_inside_window` |
| 73 | Run again | 27 / 28 Feb | Not sent twice | `test_upcoming_not_sent_twice` |
| 74 | After due date | 2 Mar | No "due soon" email | `test_no_upcoming_after_due_date` |
| 75 | Overdue | 3 Mar: no; 4 Mar: yes; 5 Mar: no | One "overdue" email | `test_overdue_sent_once_after_grace_days` |
| 76 | Already paid | Period paid in full | Skipped | `test_paid_period_skipped` |
| 77 | Contract cancelled | Before the run, or during it | No email | `test_cancelled_contract_gets_no_reminder`, `test_contract_cancelled_after_candidate_selection_is_skipped` |
| 78 | One email fails | One tenant's send raises an error | That row not flagged and no queue row; others still sent; Error Log written | `test_failed_email_leaves_row_unflagged_and_others_continue`, `test_failure_after_queueing_rolls_back_queue_row` |
| 79 | Nobody to send to | Email filtered out (unsubscribed) | Not flagged | `test_sendmail_returning_nothing_is_not_flagged` |
| 80 | Tests never save data | Run in tests | `commit=False`, nothing committed | `test_commit_false_never_commits` |
| 81 | Daily status job | Every day | Activates future contracts, releases expired ones (cases 41–43) | `AS/tasks.py` (`sync_all_shop_statuses`) |

---

## Web portal
Code: `airplane_mode/www/shops/index.py`, `index.html`, `shop.py`, `shop.html`, `AS/portal.py`, `airplane_mode/templates/shop_portal_base.html`, `airplane_mode/public/css/picnic.min.css`, `shop_portal.css`, route rule in `airplane_mode/hooks.py`. Tests: `AS/tests/test_portal.py`.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 82 | Shop list | Open `/shops` | Published shops as Picnic cards; not `web.html` | `test_rendered_pages_use_picnic_and_do_not_leak_tenant` |
| 83 | Unpublished shop | "Show on Website" unticked | Not in the list | `test_list_only_published_shops_with_public_fields` |
| 84 | Details page | `/shops/CAI-A12` | Details plus "Interested? Apply to rent" | `test_rendered_pages_use_picnic_and_do_not_leak_tenant` |
| 85 | Missing or unpublished | `/shops/NOPE` | 404 | `test_detail_hides_unpublished` |
| 86 | No tenant data | Occupied shop | Page never shows the tenant or contract | `test_public_fields_never_include_tenant_data` |
| 87 | Script in description | `<img onerror=…>` | Removed before showing | `test_description_is_sanitized_on_render` |
| 88 | Filter by airport | `/shops?airport=…` | Only that airport's shops | `www/shops/index.py` |

---

## Shop leads, tenants and connections
Code: `AS/doctype/shop_lead/shop_lead.py` (`create_tenant`, `convert_leads_for_contract`, `reopen_leads_for_contract`), `shop_lead.js`, `shop_lead_dashboard.py`; web form `AS/web_form/shop_lead/`; called from `AS/doctype/shop_contract/shop_contract.py`; reverse links in `tenant.json` and `shop_contract.json`. Tests: `AS/tests/test_shop_lead.py` and `test_portal.py`.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 89 | Visitor applies | Web form from `/shops/CAI-A12` | Lead created, status **New**, shop pre-filled; no shop list exposed | `test_lead_for_published_shop_is_accepted` |
| 90 | Lead for a hidden shop | Shop unpublished | Error: "This shop is not available." | `test_lead_for_unpublished_shop_is_rejected` |
| 91 | Create Tenant | Click on a New lead | Tenant from name/email/phone; lead → **Contacted**, linked | `test_creates_tenant_from_lead_details_and_marks_contacted` |
| 92 | Tenant already exists | Same email as an existing tenant | Existing tenant linked, no duplicate | `test_reuses_existing_tenant_with_same_email` |
| 93 | Click twice | Create Tenant again | Same tenant returned | `test_second_click_returns_same_tenant` |
| 94 | Lost lead | Create Tenant on a Lost lead | Stays Lost | `test_does_not_downgrade_a_lost_lead` |
| 95 | No permission | Travel Agent clicks | Permission error | `test_needs_write_permission_on_the_lead` |
| 96 | New Contract button | Lead has a tenant | Opens a contract with shop and tenant filled in | `shop_lead.js` |
| 97 | Auto-convert by email | Contract submitted for the lead's shop, tenant email = lead email | Lead → **Converted**, linked to the contract | `test_open_lead_with_tenant_email_is_converted_on_submit`, `test_converted_lead_links_to_its_contract` |
| 98 | Auto-convert by link | Lead linked to the tenant, emails differ | Converted | `test_lead_linked_to_tenant_is_converted_even_with_other_email` |
| 99 | Other leads | Other person, other shop, or Lost | Unchanged | `test_other_leads_are_left_alone` |
| 100 | Draft contract | Saved but not submitted | No change | `test_draft_contract_does_not_convert` |
| 101 | Contract cancelled | Cancel the converting contract | Leads back to **Contacted**, link cleared | `test_cancelled_contract_reopens_its_leads` |
| 102 | Connections on the lead | Open the lead | "Leasing" panel: Tenant 1, Shop Contract 1 | `test_lead_shows_its_tenant_and_contract` |
| 103 | Connections back | Open the tenant / contract | Shop Lead listed in their Connections | `test_tenant_and_contract_show_the_lead` |

---

## Part 3

### Shop types
Code: `airplane_mode/fixtures/shop_type.json`, fixtures in `airplane_mode/hooks.py`, `AS/doctype/shop_type/`, filter in `AS/doctype/airport_shop/airport_shop.js`.

| # | Scenario | Example | Result |
|---|---|---|---|
| 104 | Fresh install | `bench install-app airplane_mode` | Stall, Walk-through and Normal exist, all enabled |
| 105 | Disable a type | Untick **Enabled?** on Stall | Stall hidden in the shop form's Shop Type dropdown |

### REST API and permissions
Code: `bruno/airplane_mode/*.bru`, permissions in `AS/doctype/airport_shop/airport_shop.json` (permlevel 1 for tenant fields). Tests: `AS/tests/test_permissions.py`.

| # | Scenario | Example | Result | Test |
|---|---|---|---|---|
| 106 | List all fields | `GET /api/resource/Airport Shop?fields=["*"]` with an authority user's token | 200, includes tenant fields | `test_airport_authority_sees_tenant_fields` |
| 107 | Same call, Travel Agent | Travel Agent token | 200, **no** tenant/contract/expiry fields | `test_travel_agent_does_not_see_tenant_fields` |
| 108 | Create a shop | `POST /api/resource/Airport Shop` with status "Occupied" | 200; saved as **Available** | `Create Shop.bru` (case 17) |
| 109 | No token | Remove the Authorization header | 403 | `List Shops (all fields).bru` |
| 110 | Token format | `Authorization: token <api_key>:<api_secret>` | Key and secret kept as Bruno secret variables, not committed | `bruno/airplane_mode/environments/local.bru` |

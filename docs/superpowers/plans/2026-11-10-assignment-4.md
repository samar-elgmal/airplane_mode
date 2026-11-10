# Assignment 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add crew and gate tracking to flights, plus a new Airport Shops module (shops, tenants, contracts, rent schedule, partial payments, receipts, reminders, settings, report, web portal, REST API demo) to the `airplane_mode` Frappe app.

**Architecture:** Plain Frappe v15 doctypes and controllers. Doctype JSON files are written by hand in developer mode and synced with `bench migrate`. Business rules live in small modules: `airport_shops/utils.py` (pure schedule maths, shop status and counts), `airport_shops/tasks.py` (scheduler jobs) and `airport_shops/portal.py` (public website queries). Every money value goes through `flt(x, precision)`. Concurrency uses `SELECT … FOR UPDATE` on MariaDB InnoDB.

**Tech Stack:** Frappe v15.125.0, Python 3, MariaDB 10.11, Jinja, Frappe JS form API, Picnic CSS, Print Designer, Bruno.

**Spec:** `docs/superpowers/specs/2026-11-10-assignment-4-design.md`

---

## Conventions used in every task

- **Bench dir:** `/home/frappe-user/frappe-bench-dev` (run every `bench` command from here).
- **App repo:** `/home/frappe-user/frappe-bench-dev/apps/airplane_mode` (run every `git` and `python3 scripts/...` command from here). Paths below are relative to the app repo.
- **Site:** `airplane.local` (served at `http://localhost:8001`).
- **Sync doctype JSON:** `bench --site airplane.local migrate`
- **Run one test module:** `bench --site airplane.local run-tests --module <dotted.module>`
- Doctype JSON written by hand needs `"modified"` set. When you change an existing JSON file, the `scripts/add_doctype_fields.py` helper (Task 1) bumps it, so `migrate` picks the change up.
- Never commit with `git add -A`. Add the exact paths listed in each task.
- Date-dependent functions accept `on_date=None`, so tests pass dates directly (`freezegun` is **not** installed in this bench, so `FrappeTestCase.freeze_time` is unavailable).

## File map

```
scripts/add_doctype_fields.py                       dev helper: add fields to a doctype JSON
airplane_mode/hooks.py                              fixtures, scheduler_events, website_route_rules
airplane_mode/modules.txt                           + "Airport Shops"
airplane_mode/airplane_mode/tasks.py                gate background job
airplane_mode/airplane_mode/tests/                  Part 1 tests + shared factories
airplane_mode/airplane_mode/doctype/crew_member/    Crew Member
airplane_mode/airplane_mode/doctype/flight_crew_member/  child table
airplane_mode/airplane_mode/doctype/airplane_flight/     + crew, gate_number, hooks
airplane_mode/airplane_mode/doctype/airplane_ticket/     + gate_number
airplane_mode/airplane_mode/doctype/airport/             + shop count fields
airplane_mode/airport_shops/                        new module
  utils.py                                          schedule maths, sync_shop_status, counts, totals
  tasks.py                                          daily jobs, reminders
  portal.py                                         public shop queries for the website
  doctype/{shop_type,tenant,airport_shop_settings,airport_shop,rent_schedule,shop_contract,rent_payment,shop_lead}/
  report/airport_shop_occupancy/
  web_form/shop_lead/
  tests/                                            factories + tests for the module
airplane_mode/fixtures/shop_type.json
airplane_mode/templates/shop_portal_base.html
airplane_mode/templates/emails/{rent_reminder,rent_overdue}.html
airplane_mode/www/shops/{__init__.py,index.html,index.py,shop.html,shop.py}
airplane_mode/public/css/{picnic.min.css,shop_portal.css}
bruno/airplane_mode/...
```

---

### Task 0: Setup and safety net

**Files:** none in the app (site config only).

- [ ] **Step 1: Commit the existing Assignment 1–3 work first** (it is untracked right now; new commits must not mix with it). Ask the user to confirm, then:

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git status --short
git add airplane_mode/hooks.py airplane_mode/patches.txt airplane_mode/airplane_mode airplane_mode/fixtures airplane_mode/patches airplane_mode/www
git commit -m "feat: assignments 1-3 (doctypes, reports, web form, patches)"
```

- [ ] **Step 2: Allow tests on the dev site**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local set-config allow_tests true
```

- [ ] **Step 3: Check that the web server, worker and scheduler are running**

```bash
curl -s http://localhost:8001/api/method/ping          # expect {"message":"pong"}
bench doctor                                            # expect workers online, scheduler enabled
bench --site airplane.local enable-scheduler            # if doctor says disabled
```

If `bench doctor` shows no workers, start the bench with `bench start` in a separate terminal (it runs web, worker and schedule).

- [ ] **Step 4: Install Print Designer early (riskiest dependency)**

```bash
cd /home/frappe-user/frappe-bench-dev
bench get-app print_designer --branch version-15
bench --site airplane.local install-app print_designer
bench build --app print_designer
```

Expected: the install finishes and "Print Designer" appears in the desk sidebar. If the build fails on Node 18.19, note the error and continue. Task 11 has a Jinja fallback, and only the receipt depends on this.

- [ ] **Step 5: Download Picnic CSS**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
mkdir -p airplane_mode/public/css
curl -fsSL https://cdn.jsdelivr.net/npm/picnic@7.1.0/picnic.min.css -o airplane_mode/public/css/picnic.min.css
head -c 120 airplane_mode/public/css/picnic.min.css; echo
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/assets/airplane_mode/css/picnic.min.css   # expect 200
```

If the last command prints 404, run `bench build --app airplane_mode` (it links `public/` into `sites/assets`).

- [ ] **Step 6: Commit**

```bash
git add airplane_mode/public/css/picnic.min.css
git commit -m "chore: add picnic css for the shop portal"
```

---

### Task 1: Crew Member, Flight Crew Member, crew validation (Part 1)

**Files:**
- Create: `scripts/add_doctype_fields.py`
- Create: `airplane_mode/airplane_mode/doctype/crew_member/{__init__.py,crew_member.json,crew_member.py}`
- Create: `airplane_mode/airplane_mode/doctype/flight_crew_member/{__init__.py,flight_crew_member.json,flight_crew_member.py}`
- Modify: `airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.json` (via script)
- Modify: `airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.py`
- Create: `airplane_mode/airplane_mode/tests/{__init__.py,factories.py,test_crew_and_gate.py}`

- [ ] **Step 1: Create the JSON helper script**

`scripts/add_doctype_fields.py`:

```python
"""Add or replace fields in a Frappe DocType JSON file and bump `modified`.

Usage:
    python3 scripts/add_doctype_fields.py <doctype.json> '<json list of field dicts>' [--after FIELDNAME]

Fields whose fieldname already exists are replaced in place; new fields are inserted
into field_order after --after (or appended at the end).
"""
import argparse
import json
from datetime import datetime


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("path")
	parser.add_argument("fields")
	parser.add_argument("--after")
	args = parser.parse_args()

	with open(args.path) as f:
		doc = json.load(f)
	new_fields = json.loads(args.fields)

	index_by_name = {field["fieldname"]: i for i, field in enumerate(doc["fields"])}
	order = doc.setdefault("field_order", [field["fieldname"] for field in doc["fields"]])
	insert_at = order.index(args.after) + 1 if args.after else len(order)

	for field in new_fields:
		name = field["fieldname"]
		if name in index_by_name:
			doc["fields"][index_by_name[name]] = field
			continue
		doc["fields"].append(field)
		order.insert(insert_at, name)
		insert_at += 1

	doc["modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
	with open(args.path, "w") as f:
		json.dump(doc, f, indent=1, ensure_ascii=False)
		f.write("\n")


if __name__ == "__main__":
	main()
```

- [ ] **Step 2: Create Crew Member**

`airplane_mode/airplane_mode/doctype/crew_member/__init__.py`: empty file.

`airplane_mode/airplane_mode/doctype/crew_member/crew_member.json`:

```json
{
 "actions": [],
 "autoname": "CREW-.####",
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["full_name", "crew_role", "column_break_1", "email", "phone"],
 "fields": [
  {"fieldname": "full_name", "fieldtype": "Data", "label": "Full Name", "reqd": 1, "in_list_view": 1},
  {"fieldname": "crew_role", "fieldtype": "Select", "label": "Crew Role", "options": "Pilot\nCo-Pilot\nCabin Crew\nFlight Engineer", "reqd": 1, "in_list_view": 1},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "email", "fieldtype": "Data", "label": "Email", "options": "Email"},
  {"fieldname": "phone", "fieldtype": "Data", "label": "Phone", "options": "Phone"}
 ],
 "links": [],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airplane Mode",
 "name": "Crew Member",
 "naming_rule": "Expression",
 "owner": "Administrator",
 "permissions": [
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1},
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "Fleet Manager", "share": 1, "write": 1},
  {"read": 1, "report": 1, "role": "Flight Crew Member"}
 ],
 "show_title_field_in_link": 1,
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "title_field": "full_name"
}
```

`airplane_mode/airplane_mode/doctype/crew_member/crew_member.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CrewMember(Document):
	pass
```

- [ ] **Step 3: Create Flight Crew Member (child table)**

`airplane_mode/airplane_mode/doctype/flight_crew_member/__init__.py`: empty file.

`airplane_mode/airplane_mode/doctype/flight_crew_member/flight_crew_member.json`:

```json
{
 "actions": [],
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "field_order": ["crew_member", "full_name", "crew_role"],
 "fields": [
  {"fieldname": "crew_member", "fieldtype": "Link", "label": "Crew Member", "options": "Crew Member", "reqd": 1, "in_list_view": 1},
  {"fieldname": "full_name", "fieldtype": "Data", "label": "Full Name", "fetch_from": "crew_member.full_name", "read_only": 1, "in_list_view": 1},
  {"fieldname": "crew_role", "fieldtype": "Data", "label": "Crew Role", "fetch_from": "crew_member.crew_role", "read_only": 1, "in_list_view": 1}
 ],
 "istable": 1,
 "links": [],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airplane Mode",
 "name": "Flight Crew Member",
 "owner": "Administrator",
 "permissions": [],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": []
}
```

`airplane_mode/airplane_mode/doctype/flight_crew_member/flight_crew_member.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class FlightCrewMember(Document):
	pass
```

- [ ] **Step 4: Add crew section and gate number to Airplane Flight JSON**

Gate is added now as well, so the flight JSON changes only once:

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
python3 scripts/add_doctype_fields.py airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.json \
  '[{"fieldname": "gate_number", "fieldtype": "Data", "label": "Gate Number", "allow_on_submit": 1, "in_list_view": 1}]' \
  --after time_of_departure
python3 scripts/add_doctype_fields.py airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.json \
  '[{"fieldname": "crew_section", "fieldtype": "Section Break", "label": "Crew"},
    {"fieldname": "crew", "fieldtype": "Table", "label": "Crew", "options": "Flight Crew Member"}]'
```

- [ ] **Step 5: Sync**

```bash
cd /home/frappe-user/frappe-bench-dev && bench --site airplane.local migrate
```

Expected: finishes without errors; `/app/crew-member/new` opens in the desk.

- [ ] **Step 6: Write the shared test factories**

`airplane_mode/airplane_mode/tests/__init__.py`: empty file.

`airplane_mode/airplane_mode/tests/factories.py`:

```python
"""Small builders for test records. Every call creates fresh, uniquely named records."""
import frappe
from frappe.utils import add_days, today


def unique(prefix):
	return f"{prefix}-{frappe.generate_hash(length=6)}"


def make_airport(code=None):
	code = code or frappe.generate_hash(length=3).upper()
	doc = frappe.get_doc({"doctype": "Airport", "code": code, "city": "Test City", "country": "Testland"})
	doc.name = unique(f"Test Airport {code}")  # Airport uses Prompt naming
	return doc.insert()


def make_crew_member(role="Pilot"):
	return frappe.get_doc({"doctype": "Crew Member", "full_name": unique("Crew"), "crew_role": role}).insert()


def make_flight(capacity=20, submit=False, gate_number=None):
	airline = frappe.get_doc({"doctype": "Airline", "customer_care_number": "100", "headquarters": "Cairo"})
	airline.name = unique("Test Airline")  # Airline uses Prompt naming
	airline.insert()
	airplane = frappe.get_doc(
		{"doctype": "Airplane", "model": "A320", "airline": airline.name, "capacity": capacity}
	).insert()
	flight = frappe.get_doc(
		{
			"doctype": "Airplane Flight",
			"airplane": airplane.name,
			"date_of_departure": add_days(today(), 7),
			"time_of_departure": "10:00:00",
			"duration": 7200,
			"source_airport": make_airport().name,
			"destination_airport": make_airport().name,
			"gate_number": gate_number,
		}
	).insert()
	if submit:
		flight.submit()
	return flight


def make_ticket(flight, submit=False):
	passenger = frappe.get_doc(
		{"doctype": "Flight Passenger", "first_name": unique("Pax"), "date_of_birth": "1990-01-01"}
	).insert()
	ticket = frappe.get_doc(
		{
			"doctype": "Airplane Ticket",
			"passenger": passenger.name,
			"flight": flight.name,
			"flight_price": 100,
			"status": "Boarded" if submit else "Booked",
		}
	).insert()
	if submit:
		ticket.submit()
	return ticket
```

- [ ] **Step 7: Write the failing crew tests**

`airplane_mode/airplane_mode/tests/test_crew_and_gate.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airplane_mode.tests.factories import make_crew_member, make_flight


class TestFlightCrew(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_duplicate_crew_member_is_rejected(self):
		flight = make_flight()
		pilot = make_crew_member("Pilot")
		flight.append("crew", {"crew_member": pilot.name})
		flight.append("crew", {"crew_member": pilot.name})
		with self.assertRaises(frappe.ValidationError):
			flight.save()

	def test_crew_role_comes_from_crew_member(self):
		flight = make_flight()
		pilot = make_crew_member("Pilot")
		flight.append("crew", {"crew_member": pilot.name, "crew_role": "Cabin Crew"})  # tampered value
		flight.save()
		self.assertEqual(flight.crew[0].crew_role, "Pilot")
```

- [ ] **Step 8: Run it and see it fail**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local run-tests --module airplane_mode.airplane_mode.tests.test_crew_and_gate
```

Expected: `test_duplicate_crew_member_is_rejected` FAILS (no ValidationError raised). `test_crew_role_comes_from_crew_member` may pass already because of `fetch_from`. That's fine, it guards the server-side rule.

- [ ] **Step 9: Implement crew validation**

Replace `airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.py` with:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.website.website_generator import WebsiteGenerator


class AirplaneFlight(WebsiteGenerator):
	def validate(self):
		super().validate()
		self.validate_crew()

	def on_submit(self):
		self.status = "Completed"
		self.db_update()

	def validate_crew(self):
		seen = set()
		for row in self.crew:
			if row.crew_member in seen:
				frappe.throw(_("Row {0}: {1} is already on this flight's crew.").format(row.idx, row.crew_member))
			seen.add(row.crew_member)
			# fetch_from is only a UI convenience; the master is the source of truth.
			row.crew_role = frappe.db.get_value("Crew Member", row.crew_member, "crew_role")
```

- [ ] **Step 10: Run tests, see them pass**

Run the same command as Step 8. Expected: 2 tests, OK.

- [ ] **Step 11: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add scripts/add_doctype_fields.py \
  airplane_mode/airplane_mode/doctype/crew_member airplane_mode/airplane_mode/doctype/flight_crew_member \
  airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.json \
  airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.py \
  airplane_mode/airplane_mode/tests
git commit -m "feat: track crew members on flights"
```

---

### Task 2: Gate number on tickets + background job (Part 1)

**Files:**
- Modify: `airplane_mode/airplane_mode/doctype/airplane_ticket/airplane_ticket.json` (via script)
- Create: `airplane_mode/airplane_mode/tasks.py`
- Modify: `airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.py`
- Modify: `airplane_mode/airplane_mode/tests/test_crew_and_gate.py`

- [ ] **Step 1: Add `gate_number` to Airplane Ticket**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
python3 scripts/add_doctype_fields.py airplane_mode/airplane_mode/doctype/airplane_ticket/airplane_ticket.json \
  '[{"fieldname": "gate_number", "fieldtype": "Data", "label": "Gate Number", "fetch_from": "flight.gate_number", "read_only": 1, "allow_on_submit": 1, "in_list_view": 1}]' \
  --after seat
cd /home/frappe-user/frappe-bench-dev && bench --site airplane.local migrate
```

- [ ] **Step 2: Write the failing gate tests** (append to `test_crew_and_gate.py`)

```python
from unittest.mock import patch

from airplane_mode.airplane_mode.tasks import update_ticket_gate_numbers
from airplane_mode.airplane_mode.tests.factories import make_ticket

GATE_JOB = "airplane_mode.airplane_mode.tasks.update_ticket_gate_numbers"


def gate_job_calls(mock_enqueue):
	return [c for c in mock_enqueue.call_args_list if c.args and c.args[0] == GATE_JOB]


class TestGateNumber(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_new_ticket_gets_flight_gate(self):
		flight = make_flight(gate_number="A1")
		self.assertEqual(make_ticket(flight).gate_number, "A1")

	def test_job_updates_draft_and_submitted_tickets(self):
		flight = make_flight(gate_number="A1")
		draft, submitted = make_ticket(flight), make_ticket(flight, submit=True)
		frappe.db.set_value("Airplane Flight", flight.name, "gate_number", "B7")

		update_ticket_gate_numbers(flight.name)

		self.assertEqual(frappe.db.get_value("Airplane Ticket", draft.name, "gate_number"), "B7")
		self.assertEqual(frappe.db.get_value("Airplane Ticket", submitted.name, "gate_number"), "B7")

	def test_job_reads_current_gate_and_is_idempotent(self):
		flight = make_flight(gate_number="A1")
		ticket = make_ticket(flight)
		frappe.db.set_value("Airplane Flight", flight.name, "gate_number", "C3")

		self.assertEqual(update_ticket_gate_numbers(flight.name), 1)
		self.assertEqual(update_ticket_gate_numbers(flight.name), 0)  # second run changes nothing
		self.assertEqual(frappe.db.get_value("Airplane Ticket", ticket.name, "gate_number"), "C3")

	def test_gate_change_after_submit_enqueues_exactly_one_job(self):
		flight = make_flight(gate_number="A1", submit=True)
		flight.reload()
		with patch("frappe.enqueue") as enqueue:
			flight.gate_number = "D4"
			flight.save()
		calls = gate_job_calls(enqueue)
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0].kwargs["flight"], flight.name)
		self.assertTrue(calls[0].kwargs["enqueue_after_commit"])
		self.assertNotIn("deduplicate", calls[0].kwargs)

	def test_save_without_gate_change_enqueues_nothing(self):
		flight = make_flight(gate_number="A1")
		with patch("frappe.enqueue") as enqueue:
			flight.save()
		self.assertEqual(gate_job_calls(enqueue), [])

	def test_two_quick_changes_end_on_latest_gate(self):
		flight = make_flight(gate_number="A1", submit=True)
		ticket = make_ticket(flight)
		flight.reload()
		with patch("frappe.enqueue") as enqueue:
			flight.gate_number = "B2"
			flight.save()
			flight.gate_number = "C3"
			flight.save()
		self.assertEqual(len(gate_job_calls(enqueue)), 2)
		update_ticket_gate_numbers(flight.name)  # whichever job runs last
		self.assertEqual(frappe.db.get_value("Airplane Ticket", ticket.name, "gate_number"), "C3")
```

- [ ] **Step 3: Run and see failures**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local run-tests --module airplane_mode.airplane_mode.tests.test_crew_and_gate
```

Expected: ImportError for `airplane_mode.airplane_mode.tasks`.

- [ ] **Step 4: Implement the job**

`airplane_mode/airplane_mode/tasks.py`:

```python
import frappe


def update_ticket_gate_numbers(flight):
	"""Copy the flight's *current* gate onto all its non-cancelled tickets.

	The gate is read from the DB (not passed in), so running this twice, or after two quick
	gate changes, always leaves tickets on the latest gate. Returns how many tickets changed.
	"""
	gate = frappe.db.get_value("Airplane Flight", flight, "gate_number")
	tickets = frappe.get_all(
		"Airplane Ticket",
		filters={"flight": flight, "docstatus": ["<", 2]},
		fields=["name", "gate_number"],
	)
	changed = 0
	for ticket in tickets:
		if (ticket.gate_number or "") != (gate or ""):
			# set_value skips validation, so submitted tickets can be updated too.
			frappe.db.set_value("Airplane Ticket", ticket.name, "gate_number", gate)
			changed += 1
	return changed
```

- [ ] **Step 5: Trigger it from the flight**

Replace `airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.py` with:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.website.website_generator import WebsiteGenerator


class AirplaneFlight(WebsiteGenerator):
	def validate(self):
		super().validate()
		self.validate_crew()

	def on_update(self):
		super().on_update()
		self.enqueue_gate_update()

	def on_submit(self):
		self.status = "Completed"
		self.db_update()

	def on_update_after_submit(self):
		self.enqueue_gate_update()

	def validate_crew(self):
		seen = set()
		for row in self.crew:
			if row.crew_member in seen:
				frappe.throw(_("Row {0}: {1} is already on this flight's crew.").format(row.idx, row.crew_member))
			seen.add(row.crew_member)
			# fetch_from is only a UI convenience; the master is the source of truth.
			row.crew_role = frappe.db.get_value("Crew Member", row.crew_member, "crew_role")

	def enqueue_gate_update(self):
		# A brand-new flight has no tickets yet, so there is nothing to update.
		if not self.get_doc_before_save() or not self.has_value_changed("gate_number"):
			return
		# No job_id/deduplicate: in v15 dedupe also skips while the old job is STARTED,
		# which could drop the latest gate. The job is idempotent, so extra runs are safe.
		frappe.enqueue(
			"airplane_mode.airplane_mode.tasks.update_ticket_gate_numbers",
			flight=self.name,
			queue="short",
			enqueue_after_commit=True,
		)
```

- [ ] **Step 6: Run tests, see them pass**

Same command as Step 3. Expected: 8 tests OK.

- [ ] **Step 7: Manual check with the real worker**

In the desk, open a submitted flight with tickets, change Gate Number and click **Update**. Wait a few seconds and open one of its tickets: the gate shows the new value. You can also see the finished job under **RQ Job** (`/app/rq-job`).

- [ ] **Step 8: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airplane_mode/doctype/airplane_ticket/airplane_ticket.json \
  airplane_mode/airplane_mode/doctype/airplane_flight/airplane_flight.py \
  airplane_mode/airplane_mode/tasks.py airplane_mode/airplane_mode/tests/test_crew_and_gate.py
git commit -m "feat: gate number on tickets, updated by a background job"
```

---

### Task 3: Airport Shops module + Shop Type + fixtures (Part 2.1, Part 3)

**Files:**
- Modify: `airplane_mode/modules.txt`
- Create: `airplane_mode/airport_shops/__init__.py`, `airplane_mode/airport_shops/doctype/__init__.py`
- Create: `airplane_mode/airport_shops/doctype/shop_type/{__init__.py,shop_type.json,shop_type.py}`
- Create: `airplane_mode/fixtures/shop_type.json`
- Modify: `airplane_mode/hooks.py`

- [ ] **Step 1: Register the module**

Change `airplane_mode/modules.txt` to:

```
Airplane Mode
Airport Shops
```

Create empty `airplane_mode/airport_shops/__init__.py` and `airplane_mode/airport_shops/doctype/__init__.py`.

- [ ] **Step 2: Create Shop Type**

`airplane_mode/airport_shops/doctype/shop_type/__init__.py`: empty file.

`airplane_mode/airport_shops/doctype/shop_type/shop_type.json`:

```json
{
 "actions": [],
 "autoname": "field:shop_type_name",
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["shop_type_name", "enabled"],
 "fields": [
  {"fieldname": "shop_type_name", "fieldtype": "Data", "label": "Shop Type Name", "reqd": 1, "unique": 1, "in_list_view": 1},
  {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled?", "default": "1", "in_list_view": 1}
 ],
 "links": [],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Shop Type",
 "naming_rule": "By fieldname",
 "owner": "Administrator",
 "permissions": [
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1},
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "Airport Authority Personnel", "share": 1, "write": 1},
  {"read": 1, "role": "Travel Agent"}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": []
}
```

`airplane_mode/airport_shops/doctype/shop_type/shop_type.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ShopType(Document):
	pass
```

- [ ] **Step 3: Ship the three types as a fixture**

`airplane_mode/fixtures/shop_type.json`:

```json
[
 {"docstatus": 0, "doctype": "Shop Type", "enabled": 1, "modified": "2026-11-10 12:00:00.000000", "name": "Stall", "shop_type_name": "Stall"},
 {"docstatus": 0, "doctype": "Shop Type", "enabled": 1, "modified": "2026-11-10 12:00:00.000000", "name": "Walk-through", "shop_type_name": "Walk-through"},
 {"docstatus": 0, "doctype": "Shop Type", "enabled": 1, "modified": "2026-11-10 12:00:00.000000", "name": "Normal", "shop_type_name": "Normal"}
]
```

In `airplane_mode/hooks.py`, replace the `fixtures = [...]` block with:

```python
fixtures = [
	{
		"dt": "Role",
		"filters": [
			[
				"name",
				"in",
				["Airport Authority Personnel", "Fleet Manager", "Travel Agent", "Flight Crew Member"],
			]
		],
	},
	{"dt": "Shop Type", "filters": [["name", "in", ["Stall", "Walk-through", "Normal"]]]},
]
```

- [ ] **Step 4: Create the Module Def record and sync**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local execute frappe.client.insert --kwargs '{"doc": {"doctype": "Module Def", "module_name": "Airport Shops", "app_name": "airplane_mode"}}'
bench --site airplane.local migrate
bench --site airplane.local execute frappe.client.get_list --kwargs '{"doctype": "Shop Type", "fields": ["name", "enabled"]}'
```

Expected: the last command prints Stall, Walk-through and Normal, all `enabled: 1`. If the Module Def insert says it already exists, continue. Check `git diff airplane_mode/modules.txt`: in developer mode Frappe may append the module line again, so keep a single `Airport Shops` line.

- [ ] **Step 5: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/modules.txt airplane_mode/airport_shops airplane_mode/fixtures/shop_type.json airplane_mode/hooks.py
git commit -m "feat: airport shops module with shop types shipped as fixtures"
```

---

### Task 4: Tenant and Airport Shop Settings (Part 2.2, 2.7)

**Files:**
- Create: `airplane_mode/airport_shops/doctype/tenant/{__init__.py,tenant.json,tenant.py}`
- Create: `airplane_mode/airport_shops/doctype/airport_shop_settings/{__init__.py,airport_shop_settings.json,airport_shop_settings.py,airport_shop_settings.js}`
- Create: `airplane_mode/airport_shops/tests/{__init__.py,test_settings.py}`

- [ ] **Step 1: Create Tenant**

`airplane_mode/airport_shops/doctype/tenant/__init__.py`: empty file.

`airplane_mode/airport_shops/doctype/tenant/tenant.json`:

```json
{
 "actions": [],
 "autoname": "TEN-.####",
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["tenant_name", "company", "column_break_1", "email", "phone"],
 "fields": [
  {"fieldname": "tenant_name", "fieldtype": "Data", "label": "Tenant Name", "reqd": 1, "in_list_view": 1},
  {"fieldname": "company", "fieldtype": "Data", "label": "Company", "in_list_view": 1},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "email", "fieldtype": "Data", "label": "Email", "options": "Email", "reqd": 1, "in_list_view": 1},
  {"fieldname": "phone", "fieldtype": "Data", "label": "Phone", "options": "Phone"}
 ],
 "links": [{"link_doctype": "Shop Contract", "link_fieldname": "tenant"}],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Tenant",
 "naming_rule": "Expression",
 "owner": "Administrator",
 "permissions": [
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1},
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "Airport Authority Personnel", "share": 1, "write": 1}
 ],
 "show_title_field_in_link": 1,
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "title_field": "tenant_name"
}
```

> The `links` entry points at Shop Contract, which only arrives in Task 7. That's fine: during `migrate`, Frappe imports doctype JSON with validation off and skips the links-table check (`frappe.flags.in_migrate`), so the order doesn't matter.

`airplane_mode/airport_shops/doctype/tenant/tenant.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class Tenant(Document):
	pass
```

- [ ] **Step 2: Create Airport Shop Settings (Single)**

`airplane_mode/airport_shops/doctype/airport_shop_settings/__init__.py`: empty file.

`airplane_mode/airport_shops/doctype/airport_shop_settings/airport_shop_settings.json`:

```json
{
 "actions": [],
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["default_rent_amount", "reminders_section", "enable_rent_reminders", "reminder_days_before", "overdue_after_days"],
 "fields": [
  {"fieldname": "default_rent_amount", "fieldtype": "Currency", "label": "Default Rent Amount (per month)"},
  {"fieldname": "reminders_section", "fieldtype": "Section Break", "label": "Rent Reminders"},
  {"fieldname": "enable_rent_reminders", "fieldtype": "Check", "label": "Enable Rent Reminders", "default": "0"},
  {"fieldname": "reminder_days_before", "fieldtype": "Int", "label": "Send Reminder (days before due date)", "default": "3", "depends_on": "enable_rent_reminders"},
  {"fieldname": "overdue_after_days", "fieldtype": "Int", "label": "Send Overdue Reminder (days after due date)", "default": "3", "depends_on": "enable_rent_reminders"}
 ],
 "issingle": 1,
 "links": [],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Airport Shop Settings",
 "owner": "Administrator",
 "permissions": [
  {"create": 1, "email": 1, "print": 1, "read": 1, "role": "System Manager", "share": 1, "write": 1},
  {"create": 1, "email": 1, "print": 1, "read": 1, "role": "Airport Authority Personnel", "share": 1, "write": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": []
}
```

`airplane_mode/airport_shops/doctype/airport_shop_settings/airport_shop_settings.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class AirportShopSettings(Document):
	def validate(self):
		if cint(self.reminder_days_before) < 0:
			frappe.throw(_("Days before due date cannot be negative."))
		if cint(self.overdue_after_days) < 1:
			frappe.throw(_("Overdue reminder must be at least 1 day after the due date."))


@frappe.whitelist()
def enqueue_rent_reminders():
	"""Button handler: queue the reminder job instead of doing the work in the web request."""
	frappe.only_for(("System Manager", "Airport Authority Personnel"))
	frappe.enqueue(
		"airplane_mode.airport_shops.tasks.send_rent_reminders", queue="short", enqueue_after_commit=True
	)
	return _("Reminders queued")
```

`airplane_mode/airport_shops/doctype/airport_shop_settings/airport_shop_settings.js`:

```javascript
frappe.ui.form.on("Airport Shop Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Send Reminders Now"), () => {
			frappe
				.call("airplane_mode.airport_shops.doctype.airport_shop_settings.airport_shop_settings.enqueue_rent_reminders")
				.then((r) => frappe.show_alert({ message: r.message, indicator: "green" }));
		});
	},
});
```

- [ ] **Step 3: Write the settings test**

`airplane_mode/airport_shops/tests/__init__.py`: empty file.

`airplane_mode/airport_shops/tests/test_settings.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestAirportShopSettings(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_negative_days_before_rejected(self):
		settings = frappe.get_single("Airport Shop Settings")
		settings.reminder_days_before = -1
		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_overdue_days_must_be_positive(self):
		settings = frappe.get_single("Airport Shop Settings")
		settings.reminder_days_before = 3
		settings.overdue_after_days = 0
		with self.assertRaises(frappe.ValidationError):
			settings.save()
```

- [ ] **Step 4: Sync and run**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local migrate
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_settings
```

Expected: 2 tests OK. Open `/app/airport-shop-settings` and you should see the **Send Reminders Now** button. It enqueues a job that won't exist until Task 9, so don't click it yet.

- [ ] **Step 5: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airport_shops/doctype/tenant airplane_mode/airport_shops/doctype/airport_shop_settings airplane_mode/airport_shops/tests
git commit -m "feat: tenant and airport shop settings"
```

---

### Task 5: Airport Shop + airport counts (Part 2.2, 2.4, 2.5, 2.7, Part 3 filter)

**Files:**
- Modify: `airplane_mode/airplane_mode/doctype/airport/airport.json` (via script)
- Create: `airplane_mode/airport_shops/utils.py`
- Create: `airplane_mode/airport_shops/doctype/airport_shop/{__init__.py,airport_shop.json,airport_shop.py,airport_shop.js}`
- Create: `airplane_mode/airport_shops/tests/{factories.py,test_airport_shop.py}`

- [ ] **Step 1: Add shop count fields to Airport**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
python3 scripts/add_doctype_fields.py airplane_mode/airplane_mode/doctype/airport/airport.json \
  '[{"fieldname": "shops_section", "fieldtype": "Section Break", "label": "Shops"},
    {"fieldname": "total_shops", "fieldtype": "Int", "label": "Total Shops", "read_only": 1, "default": "0"},
    {"fieldname": "column_break_shops_1", "fieldtype": "Column Break"},
    {"fieldname": "available_shops", "fieldtype": "Int", "label": "Available Shops", "read_only": 1, "default": "0"},
    {"fieldname": "column_break_shops_2", "fieldtype": "Column Break"},
    {"fieldname": "occupied_shops", "fieldtype": "Int", "label": "Occupied Shops", "read_only": 1, "default": "0"}]'
```

- [ ] **Step 2: Create Airport Shop**

`airplane_mode/airport_shops/doctype/airport_shop/__init__.py`: empty file.

`airplane_mode/airport_shops/doctype/airport_shop/airport_shop.json`:

```json
{
 "actions": [],
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["shop_number", "shop_name", "airport", "shop_type", "column_break_1", "status", "current_tenant", "contract_expiry", "details_section", "area", "rent_amount", "column_break_2", "published", "image", "description_section", "description"],
 "fields": [
  {"fieldname": "shop_number", "fieldtype": "Data", "label": "Shop Number", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "shop_name", "fieldtype": "Data", "label": "Shop Name", "reqd": 1, "in_list_view": 1},
  {"fieldname": "airport", "fieldtype": "Link", "label": "Airport", "options": "Airport", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "shop_type", "fieldtype": "Link", "label": "Shop Type", "options": "Shop Type", "in_standard_filter": 1},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "Available\nOccupied", "default": "Available", "read_only": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "current_tenant", "fieldtype": "Link", "label": "Current Tenant", "options": "Tenant", "read_only": 1, "permlevel": 1},
  {"fieldname": "contract_expiry", "fieldtype": "Date", "label": "Contract Expiry", "read_only": 1, "permlevel": 1},
  {"fieldname": "details_section", "fieldtype": "Section Break", "label": "Details"},
  {"fieldname": "area", "fieldtype": "Float", "label": "Area (sq ft)", "non_negative": 1},
  {"fieldname": "rent_amount", "fieldtype": "Currency", "label": "Rent Amount (per month)", "non_negative": 1},
  {"fieldname": "column_break_2", "fieldtype": "Column Break"},
  {"fieldname": "published", "fieldtype": "Check", "label": "Show on Website", "default": "1"},
  {"fieldname": "image", "fieldtype": "Attach Image", "label": "Image"},
  {"fieldname": "description_section", "fieldtype": "Section Break", "label": "Description"},
  {"fieldname": "description", "fieldtype": "Text Editor", "label": "Description"}
 ],
 "image_field": "image",
 "links": [],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Airport Shop",
 "owner": "Administrator",
 "permissions": [
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1},
  {"permlevel": 1, "read": 1, "role": "System Manager"},
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "Airport Authority Personnel", "share": 1, "write": 1},
  {"permlevel": 1, "read": 1, "role": "Airport Authority Personnel"},
  {"read": 1, "report": 1, "role": "Travel Agent"}
 ],
 "show_title_field_in_link": 1,
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "title_field": "shop_name"
}
```

`airplane_mode/airport_shops/doctype/airport_shop/airport_shop.js`:

```javascript
frappe.ui.form.on("Airport Shop", {
	setup(frm) {
		frm.set_query("shop_type", () => ({ filters: { enabled: 1 } }));
	},
});
```

- [ ] **Step 3: Write test factories for the module**

`airplane_mode/airport_shops/tests/factories.py`:

```python
import frappe

from airplane_mode.airplane_mode.tests.factories import make_airport, unique

__all__ = [
	"make_airport",
	"make_shop",
	"make_tenant",
	"make_contract",
	"make_payment",
	"ensure_outgoing_email_account",
]


def make_shop(airport=None, number=None, rent=1000, **extra):
	airport = airport or make_airport()
	return frappe.get_doc(
		{
			"doctype": "Airport Shop",
			"airport": airport.name if hasattr(airport, "name") else airport,
			"shop_number": number or frappe.generate_hash(length=4).upper(),
			"shop_name": unique("Shop"),
			"shop_type": "Normal",
			"area": 120,
			"rent_amount": rent,
			**extra,
		}
	).insert()


def make_tenant(email=None):
	return frappe.get_doc(
		{"doctype": "Tenant", "tenant_name": unique("Tenant"), "email": email or f"{unique('t')}@example.com"}
	).insert()


def make_contract(shop, tenant=None, start="2026-11-15", end="2027-02-14", rent=1000, submit=True):
	tenant = tenant or make_tenant()
	doc = frappe.get_doc(
		{
			"doctype": "Shop Contract",
			"shop": shop.name,
			"tenant": tenant.name,
			"start_date": start,
			"end_date": end,
			"rent_amount": rent,
		}
	).insert()
	if submit:
		doc.submit()
	return doc


def make_payment(contract, period_start, amount, submit=True):
	doc = frappe.get_doc(
		{
			"doctype": "Rent Payment",
			"shop_contract": contract.name,
			"period_start": period_start,
			"amount": amount,
			"mode_of_payment": "Cash",
		}
	).insert()
	if submit:
		doc.submit()
	return doc


def ensure_outgoing_email_account():
	"""frappe.sendmail needs a default outgoing account. Tests skip the SMTP check."""
	if frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}):
		return
	frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_account_name": "Rent Test Outgoing",
			"email_id": "rent-test@example.com",
			"enable_outgoing": 1,
			"default_outgoing": 1,
			"smtp_server": "localhost",
			"smtp_port": 25,
			"no_smtp_authentication": 1,
		}
	).insert(ignore_permissions=True)
```

(`make_contract` and `make_payment` are used from Task 7 and Task 8.)

- [ ] **Step 4: Write failing tests**

`airplane_mode/airport_shops/tests/test_airport_shop.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.tests.factories import make_airport, make_shop, make_tenant


def counts(airport):
	return frappe.db.get_value(
		"Airport", airport, ["total_shops", "available_shops", "occupied_shops"], as_dict=True
	)


class TestAirportShop(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_name_uses_airport_code(self):
		airport = make_airport("CAI")
		shop = make_shop(airport, number="A12")
		self.assertEqual(shop.name, "CAI-A12")

	def test_duplicate_number_in_same_airport_rejected(self):
		airport = make_airport()
		make_shop(airport, number="B1")
		with self.assertRaises(frappe.ValidationError):
			make_shop(airport, number="B1")

	def test_default_rent_from_settings(self):
		frappe.db.set_single_value("Airport Shop Settings", "default_rent_amount", 750)
		shop = make_shop(rent=0)
		self.assertEqual(shop.rent_amount, 750)

	def test_insert_forces_available_and_clears_tenant(self):
		tenant = make_tenant()
		shop = make_shop(status="Occupied", current_tenant=tenant.name, contract_expiry="2030-01-01")
		self.assertEqual(shop.status, "Available")
		self.assertIsNone(shop.current_tenant)
		self.assertIsNone(shop.contract_expiry)

	def test_protected_fields_cannot_be_changed_by_save(self):
		shop = make_shop()
		shop.status = "Occupied"
		with self.assertRaises(frappe.ValidationError):
			shop.save()

	def test_airport_counts_follow_insert_and_delete(self):
		airport = make_airport()
		shop = make_shop(airport)
		make_shop(airport)
		self.assertEqual(counts(airport.name), {"total_shops": 2, "available_shops": 2, "occupied_shops": 0})
		frappe.delete_doc("Airport Shop", shop.name)
		self.assertEqual(counts(airport.name).total_shops, 1)

	def test_airport_change_updates_both_airports(self):
		old, new = make_airport(), make_airport()
		shop = make_shop(old)
		shop.airport = new.name
		shop.save()
		self.assertEqual(counts(old.name).total_shops, 0)
		self.assertEqual(counts(new.name).total_shops, 1)
```

- [ ] **Step 5: Sync and see failures**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local migrate
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_airport_shop
```

Expected: failures. The name is a hash (no `autoname` yet), and the duplicate, protected-field and count tests fail.

- [ ] **Step 6: Create `utils.py` with the counts helper**

`airplane_mode/airport_shops/utils.py`:

```python
import frappe


def update_airport_shop_counts(airport):
	"""Recompute the stored shop counts on an Airport from the Airport Shop table."""
	if not airport or not frappe.db.exists("Airport", airport):
		return
	total = frappe.db.count("Airport Shop", {"airport": airport})
	occupied = frappe.db.count("Airport Shop", {"airport": airport, "status": "Occupied"})
	frappe.db.set_value(
		"Airport",
		airport,
		{"total_shops": total, "occupied_shops": occupied, "available_shops": total - occupied},
		update_modified=False,
	)
```

- [ ] **Step 7: Implement the Airport Shop controller**

`airplane_mode/airport_shops/doctype/airport_shop/airport_shop.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt

from airplane_mode.airport_shops.utils import update_airport_shop_counts

# Only sync_shop_status (via frappe.db.set_value, which skips validate) may write these.
PROTECTED_FIELDS = ("status", "current_tenant", "contract_expiry")


class AirportShop(Document):
	def autoname(self):
		code = frappe.db.get_value("Airport", self.airport, "code") or self.airport
		self.name = f"{code}-{self.shop_number}".strip()

	def before_insert(self):
		self.status = "Available"
		for fieldname in PROTECTED_FIELDS[1:]:
			self.set(fieldname, None)
		if not flt(self.rent_amount):
			self.rent_amount = flt(frappe.db.get_single_value("Airport Shop Settings", "default_rent_amount"))

	def validate(self):
		self.validate_unique_shop_number()
		if not self.is_new():
			self.validate_protected_fields()

	def on_update(self):
		update_airport_shop_counts(self.airport)
		before = self.get_doc_before_save()
		if before and before.airport != self.airport:
			update_airport_shop_counts(before.airport)

	def after_delete(self):
		update_airport_shop_counts(self.airport)

	def validate_unique_shop_number(self):
		duplicate = frappe.db.exists(
			"Airport Shop",
			{"airport": self.airport, "shop_number": self.shop_number, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(_("Shop number {0} already exists at airport {1}.").format(self.shop_number, self.airport))

	def validate_protected_fields(self):
		before = self.get_doc_before_save()
		if not before:
			return
		for fieldname in PROTECTED_FIELDS:
			# cstr() so a date from the DB and a date string from the API compare equal.
			if cstr(before.get(fieldname)) != cstr(self.get(fieldname)):
				frappe.throw(
					_("{0} is set automatically from shop contracts and cannot be changed by hand.").format(
						self.meta.get_label(fieldname)
					)
				)
```

- [ ] **Step 8: Run the tests, see them pass**

Same command as Step 5. Expected: 7 tests OK.

- [ ] **Step 9: Manual check**

Open `/app/airport-shop/new`. The Shop Type dropdown lists only enabled types: untick **Enabled?** on "Stall" and check it disappears from the dropdown, then tick it again. Saving a shop with Rent Amount empty fills in the default from settings.

- [ ] **Step 10: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airplane_mode/doctype/airport/airport.json airplane_mode/airport_shops/utils.py \
  airplane_mode/airport_shops/doctype/airport_shop airplane_mode/airport_shops/tests/factories.py \
  airplane_mode/airport_shops/tests/test_airport_shop.py
git commit -m "feat: airport shop with protected status fields and airport shop counts"
```

---

### Task 6: Rent schedule maths (pure functions)

**Files:**
- Modify: `airplane_mode/airport_shops/utils.py`
- Create: `airplane_mode/airport_shops/tests/test_rent_schedule.py`

- [ ] **Step 1: Write failing tests**

`airplane_mode/airport_shops/tests/test_rent_schedule.py`:

```python
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, getdate

from airplane_mode.airport_shops.utils import build_rent_schedule, get_anniversary_date

D = getdate


class TestAnniversaryDate(FrappeTestCase):
	def test_month_end_does_not_drift(self):
		got = [get_anniversary_date("2027-01-31", n) for n in range(5)]
		self.assertEqual(got, [D("2027-01-31"), D("2027-02-28"), D("2027-03-31"), D("2027-04-30"), D("2027-05-31")])

	def test_leap_year_february(self):
		self.assertEqual(get_anniversary_date("2028-01-31", 1), D("2028-02-29"))

	def test_day_30(self):
		got = [get_anniversary_date("2027-01-30", n) for n in range(3)]
		self.assertEqual(got, [D("2027-01-30"), D("2027-02-28"), D("2027-03-30")])

	def test_leap_day_plus_twelve_months(self):
		self.assertEqual(get_anniversary_date("2028-02-29", 12), D("2029-02-28"))


class TestBuildRentSchedule(FrappeTestCase):
	def test_exact_three_months(self):
		rows = build_rent_schedule("2026-11-15", "2027-02-14", 1000)
		self.assertEqual([r.period_start for r in rows], [D("2026-11-15"), D("2026-12-15"), D("2027-01-15")])
		self.assertEqual(rows[-1].period_end, D("2027-02-14"))
		self.assertEqual([r.amount for r in rows], [1000, 1000, 1000])

	def test_short_last_period_is_prorated_by_days(self):
		rows = build_rent_schedule("2026-11-15", "2027-02-15", 1000)
		self.assertEqual(len(rows), 4)
		last = rows[-1]
		self.assertEqual((last.period_start, last.period_end), (D("2027-02-15"), D("2027-02-15")))
		# full period would be 15 Feb – 14 Mar 2027 = 28 days
		self.assertEqual(last.amount, flt(1000 / 28, 2))

	def test_31st_start_uses_anniversaries(self):
		rows = build_rent_schedule("2027-01-31", "2027-04-29", 1000)
		self.assertEqual([r.period_start for r in rows], [D("2027-01-31"), D("2027-02-28"), D("2027-03-31")])
		self.assertEqual([r.amount for r in rows], [1000, 1000, 1000])  # 31 Mar – 29 Apr is a full period

	def test_precision_of_prorated_amount(self):
		rows = build_rent_schedule("2026-12-01", "2027-01-10", 1000)
		self.assertEqual(rows[1].amount, 322.58)  # 1000 × 10 / 31

	def test_rows_start_unpaid_and_due_on_period_start(self):
		for row in build_rent_schedule("2026-11-15", "2027-02-14", 1000):
			self.assertEqual(row.due_date, row.period_start)
			self.assertEqual(row.status, "Unpaid")
			self.assertEqual(row.paid_amount, 0)
			self.assertEqual(row.outstanding_amount, row.amount)

	def test_contract_shorter_than_a_month(self):
		rows = build_rent_schedule("2026-12-01", "2026-12-10", 1000)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].amount, 322.58)
```

- [ ] **Step 2: Run, see ImportError**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_rent_schedule
```

- [ ] **Step 3: Implement** (add to the top part of `airplane_mode/airport_shops/utils.py`, keeping `update_airport_shop_counts`)

```python
import frappe
from frappe.utils import add_days, add_months, date_diff, flt, getdate


def get_anniversary_date(start_date, months):
	"""start_date + N months, always computed from the ORIGINAL start date.

	add_months uses relativedelta, which clamps to the month's last day without drifting:
	31 Jan -> 28 Feb -> 31 Mar (not 28 Mar).
	"""
	return getdate(add_months(getdate(start_date), months))


def build_rent_schedule(start_date, end_date, rent_amount, precision=2):
	"""Split [start_date, end_date] (both inclusive) into anniversary periods.

	Each period runs from one anniversary to the day before the next. Full periods cost
	rent_amount. A last period cut short by end_date is prorated by days against the
	length of the full period it belongs to.
	"""
	start, end = getdate(start_date), getdate(end_date)
	rows = []
	n = 0
	while True:
		period_start = get_anniversary_date(start, n)
		if period_start > end:
			break
		full_period_end = getdate(add_days(get_anniversary_date(start, n + 1), -1))
		period_end = min(full_period_end, end)
		if period_end == full_period_end:
			amount = flt(rent_amount, precision)
		else:
			days = date_diff(period_end, period_start) + 1
			full_days = date_diff(full_period_end, period_start) + 1
			amount = flt(flt(rent_amount) * days / full_days, precision)
		rows.append(
			frappe._dict(
				period_start=period_start,
				period_end=period_end,
				due_date=period_start,
				amount=amount,
				paid_amount=0,
				outstanding_amount=amount,
				status="Unpaid",
			)
		)
		n += 1
	return rows
```

> Note: the full period for proration is "this anniversary to the day before the next one". It matches the schedule's own periods, and differs from the spec's "+1 month − 1 day" only for month-end starts. Task 14 updates the spec wording.

- [ ] **Step 4: Run, see pass**

Same command. Expected: 10 tests OK.

- [ ] **Step 5: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airport_shops/utils.py airplane_mode/airport_shops/tests/test_rent_schedule.py
git commit -m "feat: anniversary rent schedule with day proration"
```

---

### Task 7: Rent Schedule + Shop Contract + sync_shop_status (Part 2.2, 2.4, 2.5)

**Files:**
- Create: `airplane_mode/airport_shops/doctype/rent_schedule/{__init__.py,rent_schedule.json,rent_schedule.py}`
- Create: `airplane_mode/airport_shops/doctype/shop_contract/{__init__.py,shop_contract.json,shop_contract.py,shop_contract.js}`
- Modify: `airplane_mode/airport_shops/doctype/airport_shop/airport_shop.json` (via script), `airport_shop.py`
- Modify: `airplane_mode/airport_shops/utils.py`
- Create: `airplane_mode/airport_shops/tests/test_shop_contract.py`

- [ ] **Step 1: Create Rent Schedule (child)**

`airplane_mode/airport_shops/doctype/rent_schedule/__init__.py`: empty file.

`airplane_mode/airport_shops/doctype/rent_schedule/rent_schedule.json` (the Email Queue links are part of the reminder work in Task 9, but they're created now so this table is built once):

```json
{
 "actions": [],
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["period_start", "period_end", "due_date", "amount", "paid_amount", "outstanding_amount", "status", "reminder_sent_on", "reminder_email", "overdue_reminder_sent_on", "overdue_reminder_email"],
 "fields": [
  {"fieldname": "period_start", "fieldtype": "Date", "label": "Period Start", "read_only": 1, "in_list_view": 1},
  {"fieldname": "period_end", "fieldtype": "Date", "label": "Period End", "read_only": 1, "in_list_view": 1},
  {"fieldname": "due_date", "fieldtype": "Date", "label": "Due Date", "read_only": 1, "in_list_view": 1},
  {"fieldname": "amount", "fieldtype": "Currency", "label": "Amount", "read_only": 1, "in_list_view": 1},
  {"fieldname": "paid_amount", "fieldtype": "Currency", "label": "Paid", "read_only": 1, "in_list_view": 1},
  {"fieldname": "outstanding_amount", "fieldtype": "Currency", "label": "Outstanding", "read_only": 1, "in_list_view": 1},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "Unpaid\nPartly Paid\nPaid", "default": "Unpaid", "read_only": 1, "in_list_view": 1},
  {"fieldname": "reminder_sent_on", "fieldtype": "Date", "label": "Reminder Sent On", "read_only": 1, "no_copy": 1},
  {"fieldname": "reminder_email", "fieldtype": "Link", "label": "Reminder Email", "options": "Email Queue", "read_only": 1, "no_copy": 1},
  {"fieldname": "overdue_reminder_sent_on", "fieldtype": "Date", "label": "Overdue Reminder Sent On", "read_only": 1, "no_copy": 1},
  {"fieldname": "overdue_reminder_email", "fieldtype": "Link", "label": "Overdue Reminder Email", "options": "Email Queue", "read_only": 1, "no_copy": 1}
 ],
 "istable": 1,
 "links": [],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Rent Schedule",
 "owner": "Administrator",
 "permissions": [],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": []
}
```

`airplane_mode/airport_shops/doctype/rent_schedule/rent_schedule.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class RentSchedule(Document):
	pass
```

- [ ] **Step 2: Create Shop Contract**

`airplane_mode/airport_shops/doctype/shop_contract/__init__.py`: empty file.

`airplane_mode/airport_shops/doctype/shop_contract/shop_contract.json`:

```json
{
 "actions": [],
 "autoname": "CON-.YYYY.-.####",
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["shop", "airport", "tenant", "tenant_email", "column_break_1", "rent_amount", "start_date", "end_date", "amended_from", "schedule_section", "rent_schedule", "totals_section", "total_amount", "column_break_2", "total_paid", "column_break_3", "total_outstanding"],
 "fields": [
  {"fieldname": "shop", "fieldtype": "Link", "label": "Shop", "options": "Airport Shop", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "airport", "fieldtype": "Link", "label": "Airport", "options": "Airport", "fetch_from": "shop.airport", "read_only": 1, "in_standard_filter": 1},
  {"fieldname": "tenant", "fieldtype": "Link", "label": "Tenant", "options": "Tenant", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "tenant_email", "fieldtype": "Data", "label": "Tenant Email", "options": "Email", "fetch_from": "tenant.email", "read_only": 1},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "rent_amount", "fieldtype": "Currency", "label": "Monthly Rent", "fetch_from": "shop.rent_amount", "fetch_if_empty": 1, "reqd": 1},
  {"fieldname": "start_date", "fieldtype": "Date", "label": "Start Date", "reqd": 1, "in_list_view": 1},
  {"fieldname": "end_date", "fieldtype": "Date", "label": "End Date (last day)", "reqd": 1, "in_list_view": 1},
  {"fieldname": "amended_from", "fieldtype": "Link", "label": "Amended From", "options": "Shop Contract", "no_copy": 1, "print_hide": 1, "read_only": 1, "search_index": 1},
  {"fieldname": "schedule_section", "fieldtype": "Section Break", "label": "Rent Schedule"},
  {"fieldname": "rent_schedule", "fieldtype": "Table", "label": "Rent Schedule", "options": "Rent Schedule", "read_only": 1},
  {"fieldname": "totals_section", "fieldtype": "Section Break", "label": "Totals"},
  {"fieldname": "total_amount", "fieldtype": "Currency", "label": "Total Rent", "read_only": 1},
  {"fieldname": "column_break_2", "fieldtype": "Column Break"},
  {"fieldname": "total_paid", "fieldtype": "Currency", "label": "Total Paid", "read_only": 1},
  {"fieldname": "column_break_3", "fieldtype": "Column Break"},
  {"fieldname": "total_outstanding", "fieldtype": "Currency", "label": "Total Outstanding", "read_only": 1}
 ],
 "is_submittable": 1,
 "links": [{"link_doctype": "Rent Payment", "link_fieldname": "shop_contract"}],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Shop Contract",
 "naming_rule": "Expression",
 "owner": "Administrator",
 "permissions": [
  {"amend": 1, "cancel": 1, "create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "submit": 1, "write": 1},
  {"amend": 1, "cancel": 1, "create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "Airport Authority Personnel", "share": 1, "submit": 1, "write": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": []
}
```

> The `links` entry points at Rent Payment (Task 8). As above, migrate doesn't check it, and the connections panel starts working once Rent Payment exists.

`airplane_mode/airport_shops/doctype/shop_contract/shop_contract.js`:

```javascript
frappe.ui.form.on("Shop Contract", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Record Payment"), () => {
				frappe.new_doc("Rent Payment", { shop_contract: frm.doc.name });
			});
		}
	},
});
```

- [ ] **Step 3: Add `current_contract` and a contracts connection to Airport Shop**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
python3 scripts/add_doctype_fields.py airplane_mode/airport_shops/doctype/airport_shop/airport_shop.json \
  '[{"fieldname": "current_contract", "fieldtype": "Link", "label": "Current Contract", "options": "Shop Contract", "read_only": 1, "permlevel": 1}]' \
  --after current_tenant
python3 - <<'EOF'
import json
path = "airplane_mode/airport_shops/doctype/airport_shop/airport_shop.json"
doc = json.load(open(path))
doc["links"] = [{"link_doctype": "Shop Contract", "link_fieldname": "shop"}]
with open(path, "w") as f:
    json.dump(doc, f, indent=1)
    f.write("\n")
EOF
```

(The first command already bumped `modified` on `airport_shop.json`, so `migrate` picks up both changes.)

- [ ] **Step 4: Sync**

```bash
cd /home/frappe-user/frappe-bench-dev && bench --site airplane.local migrate
```

- [ ] **Step 5: Write failing tests**

`airplane_mode/airport_shops/tests/test_shop_contract.py`:

```python
import frappe
from frappe.utils import add_days, getdate, today

from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.tests.factories import make_airport, make_contract, make_shop, make_tenant
from airplane_mode.airport_shops.utils import sync_shop_status


def shop_state(shop):
	return frappe.db.get_value(
		"Airport Shop", shop.name, ["status", "current_tenant", "current_contract", "contract_expiry"], as_dict=True
	)


class TestShopContract(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_submit_builds_schedule_and_totals(self):
		contract = make_contract(make_shop(), start="2026-11-15", end="2027-02-15", rent=1000)
		self.assertEqual(len(contract.rent_schedule), 4)
		self.assertEqual(contract.total_amount, sum(r.amount for r in contract.rent_schedule))
		self.assertEqual(contract.total_paid, 0)
		self.assertEqual(contract.total_outstanding, contract.total_amount)

	def test_end_before_start_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_contract(make_shop(), start="2027-01-10", end="2027-01-01")

	def test_overlap_rejected_and_adjacent_allowed(self):
		shop = make_shop()
		make_contract(shop, start="2027-01-01", end="2027-03-31")
		with self.assertRaises(frappe.ValidationError):
			make_contract(shop, start="2027-03-31", end="2027-06-30")
		make_contract(shop, start="2027-04-01", end="2027-06-30")  # adjacent is fine

	def test_overlap_rechecked_on_submit(self):
		shop = make_shop()
		first = make_contract(shop, start="2027-01-01", end="2027-03-31", submit=False)
		second = make_contract(shop, start="2027-02-01", end="2027-04-30", submit=False)  # drafts don't clash
		first.submit()
		with self.assertRaises(frappe.ValidationError):
			second.submit()

	def test_active_contract_occupies_shop_and_updates_counts(self):
		airport = make_airport()
		shop = make_shop(airport)
		tenant = make_tenant()
		contract = make_contract(shop, tenant, start=add_days(today(), -10), end=add_days(today(), 50))
		state = shop_state(shop)
		self.assertEqual(state.status, "Occupied")
		self.assertEqual(state.current_tenant, tenant.name)
		self.assertEqual(state.current_contract, contract.name)
		self.assertEqual(state.contract_expiry, getdate(contract.end_date))
		self.assertEqual(frappe.db.get_value("Airport", airport.name, "occupied_shops"), 1)

	def test_future_contract_activates_on_its_start_date(self):
		shop = make_shop()
		contract = make_contract(shop, start=add_days(today(), 5), end=add_days(today(), 60))
		self.assertEqual(shop_state(shop).status, "Available")
		sync_shop_status(shop.name, on_date=contract.start_date)
		self.assertEqual(shop_state(shop).status, "Occupied")

	def test_expired_contract_releases_shop(self):
		shop = make_shop()
		contract = make_contract(shop, start=add_days(today(), -30), end=add_days(today(), 1))
		sync_shop_status(shop.name, on_date=add_days(contract.end_date, 1))
		state = shop_state(shop)
		self.assertEqual(state.status, "Available")
		self.assertIsNone(state.current_tenant)

	def test_back_to_back_contracts_switch_without_gap(self):
		shop = make_shop()
		a = make_contract(shop, start="2026-09-01", end="2026-11-30")
		b_tenant = make_tenant()
		b = make_contract(shop, b_tenant, start="2026-12-01", end="2027-05-31")
		sync_shop_status(shop.name, on_date="2026-11-30")
		self.assertEqual(shop_state(shop).current_contract, a.name)
		sync_shop_status(shop.name, on_date="2026-12-01")
		state = shop_state(shop)
		self.assertEqual(state.status, "Occupied")
		self.assertEqual(state.current_contract, b.name)
		self.assertEqual(state.current_tenant, b_tenant.name)

	def test_cancel_releases_shop(self):
		shop = make_shop()
		contract = make_contract(shop, start=add_days(today(), -1), end=add_days(today(), 30))
		contract.cancel()
		self.assertEqual(shop_state(shop).status, "Available")

	def test_amend_rebuilds_schedule(self):
		shop = make_shop()
		contract = make_contract(shop, start="2027-01-01", end="2027-03-31")
		frappe.db.set_value("Rent Schedule", contract.rent_schedule[0].name, "reminder_sent_on", "2026-12-29")
		contract.reload()
		contract.cancel()

		amended = frappe.copy_doc(contract)
		amended.amended_from = contract.name
		amended.insert()
		self.assertEqual(amended.rent_schedule, [])  # copied rows dropped on validate
		amended.submit()

		self.assertEqual(len(amended.rent_schedule), 3)
		self.assertTrue(all(r.status == "Unpaid" and not r.reminder_sent_on for r in amended.rent_schedule))
		self.assertEqual(frappe.db.count("Rent Schedule", {"parent": contract.name}), 3)  # original keeps its rows

	def test_amend_overlapping_another_contract_rejected(self):
		shop = make_shop()
		original = make_contract(shop, start="2027-01-01", end="2027-03-31")
		make_contract(shop, start="2027-04-01", end="2027-06-30")
		original.cancel()
		amended = frappe.copy_doc(original)
		amended.amended_from = original.name
		amended.end_date = "2027-04-15"  # now overlaps the second contract
		with self.assertRaises(frappe.ValidationError):
			amended.insert()

	def test_airport_change_blocked_with_active_or_future_contract(self):
		shop = make_shop()
		make_contract(shop, start=add_days(today(), 10), end=add_days(today(), 40))
		shop.reload()
		shop.airport = make_airport().name
		with self.assertRaises(frappe.ValidationError):
			shop.save()
```

- [ ] **Step 6: Run, see failures**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_shop_contract
```

Expected: ImportError for `sync_shop_status`.

- [ ] **Step 7: Add status/contract helpers to `utils.py`** (append below the existing functions)

```python
from frappe.utils import today  # add to the existing frappe.utils import line


def get_active_contract(shop, on_date=None):
	"""The submitted contract covering on_date (default today), or None.

	The overlap rule guarantees there is at most one.
	"""
	day = getdate(on_date or today())
	rows = frappe.get_all(
		"Shop Contract",
		filters={"shop": shop, "docstatus": 1, "start_date": ["<=", day], "end_date": [">=", day]},
		fields=["name", "tenant", "end_date"],
		order_by="start_date desc",
		limit=1,
	)
	return rows[0] if rows else None


def sync_shop_status(shop, on_date=None):
	"""Single source of truth for a shop's status. Recomputed from ALL submitted contracts."""
	current = frappe.db.get_value(
		"Airport Shop",
		shop,
		["airport", "status", "current_tenant", "current_contract", "contract_expiry"],
		as_dict=True,
	)
	if not current:
		return
	contract = get_active_contract(shop, on_date)
	if contract:
		target = {
			"status": "Occupied",
			"current_tenant": contract.tenant,
			"current_contract": contract.name,
			"contract_expiry": getdate(contract.end_date),
		}
	else:
		target = {"status": "Available", "current_tenant": None, "current_contract": None, "contract_expiry": None}

	if any((current.get(key) or None) != (value or None) for key, value in target.items()):
		# set_value skips Airport Shop.validate, which blocks everyone else from these fields.
		frappe.db.set_value("Airport Shop", shop, target)
	update_airport_shop_counts(current.airport)


def update_contract_totals(contract):
	"""Recompute a contract's totals from its schedule rows."""
	precision = frappe.get_precision("Shop Contract", "total_amount") or 2
	total, paid = frappe.db.sql(
		"""select coalesce(sum(amount), 0), coalesce(sum(paid_amount), 0)
		from `tabRent Schedule` where parent = %s and parenttype = 'Shop Contract'""",
		contract,
	)[0]
	frappe.db.set_value(
		"Shop Contract",
		contract,
		{
			"total_amount": flt(total, precision),
			"total_paid": flt(paid, precision),
			"total_outstanding": flt(flt(total) - flt(paid), precision),
		},
		update_modified=False,
	)
```

The final import line at the top of `utils.py` must be:

```python
from frappe.utils import add_days, add_months, date_diff, flt, getdate, today
```

- [ ] **Step 8: Implement the Shop Contract controller**

`airplane_mode/airport_shops/doctype/shop_contract/shop_contract.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from airplane_mode.airport_shops.utils import build_rent_schedule, sync_shop_status


class ShopContract(Document):
	def validate(self):
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."))
		if flt(self.rent_amount) <= 0:
			frappe.throw(_("Monthly Rent must be greater than zero."))
		self.validate_no_overlap()
		if self.docstatus == 0:
			# Drafts never carry a schedule. This also drops rows copied by Amend
			# (paid amounts, reminder flags, email links).
			self.set("rent_schedule", [])
			self.total_amount = self.total_paid = self.total_outstanding = 0

	def before_submit(self):
		# Lock the shop so two contracts for it can't be submitted at the same time,
		# then re-check the overlap while holding the lock.
		frappe.db.sql("select name from `tabAirport Shop` where name = %s for update", self.shop)
		self.validate_no_overlap()
		self.make_rent_schedule()

	def on_submit(self):
		sync_shop_status(self.shop)

	def before_cancel(self):
		# Same lock Rent Payment takes first, so a cancel and a payment can't interleave.
		frappe.db.sql("select name from `tabShop Contract` where name = %s for update", self.name)
		if frappe.db.exists("Rent Payment", {"shop_contract": self.name, "docstatus": 1}):
			frappe.throw(_("Cancel the submitted Rent Payments of this contract first."))

	def on_cancel(self):
		sync_shop_status(self.shop)

	def validate_no_overlap(self):
		clash = frappe.db.get_value(
			"Shop Contract",
			{
				"shop": self.shop,
				"docstatus": 1,
				"name": ["!=", self.name],
				"start_date": ["<=", self.end_date],
				"end_date": [">=", self.start_date],
			},
			"name",
		)
		if clash:
			frappe.throw(_("Shop {0} already has contract {1} for these dates.").format(self.shop, clash))

	def make_rent_schedule(self):
		precision = self.precision("amount", "rent_schedule") or 2
		self.set("rent_schedule", [])
		for row in build_rent_schedule(self.start_date, self.end_date, self.rent_amount, precision):
			self.append("rent_schedule", row)
		total_precision = self.precision("total_amount") or 2
		self.total_amount = flt(sum(flt(r.amount) for r in self.rent_schedule), total_precision)
		self.total_paid = 0
		self.total_outstanding = self.total_amount
```

- [ ] **Step 9: Route Airport Shop status through `sync_shop_status` and block airport changes**

Replace `airplane_mode/airport_shops/doctype/airport_shop/airport_shop.py` with:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt, today

from airplane_mode.airport_shops.utils import sync_shop_status, update_airport_shop_counts

# Only sync_shop_status (via frappe.db.set_value, which skips validate) may write these.
PROTECTED_FIELDS = ("status", "current_tenant", "current_contract", "contract_expiry")


class AirportShop(Document):
	def autoname(self):
		code = frappe.db.get_value("Airport", self.airport, "code") or self.airport
		self.name = f"{code}-{self.shop_number}".strip()

	def before_insert(self):
		self.status = "Available"
		for fieldname in PROTECTED_FIELDS[1:]:
			self.set(fieldname, None)
		if not flt(self.rent_amount):
			self.rent_amount = flt(frappe.db.get_single_value("Airport Shop Settings", "default_rent_amount"))

	def validate(self):
		self.validate_unique_shop_number()
		if not self.is_new():
			self.validate_protected_fields()
			self.validate_airport_change()

	def on_update(self):
		sync_shop_status(self.name)  # also refreshes this airport's counts
		before = self.get_doc_before_save()
		if before and before.airport != self.airport:
			update_airport_shop_counts(before.airport)

	def after_delete(self):
		update_airport_shop_counts(self.airport)

	def validate_unique_shop_number(self):
		duplicate = frappe.db.exists(
			"Airport Shop",
			{"airport": self.airport, "shop_number": self.shop_number, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(_("Shop number {0} already exists at airport {1}.").format(self.shop_number, self.airport))

	def validate_protected_fields(self):
		before = self.get_doc_before_save()
		if not before:
			return
		for fieldname in PROTECTED_FIELDS:
			# cstr() so a date from the DB and a date string from the API compare equal.
			if cstr(before.get(fieldname)) != cstr(self.get(fieldname)):
				frappe.throw(
					_("{0} is set automatically from shop contracts and cannot be changed by hand.").format(
						self.meta.get_label(fieldname)
					)
				)

	def validate_airport_change(self):
		before = self.get_doc_before_save()
		if not before or before.airport == self.airport:
			return
		if frappe.db.exists("Shop Contract", {"shop": self.name, "docstatus": 1, "end_date": [">=", today()]}):
			frappe.throw(_("This shop has an active or upcoming contract, so its airport cannot be changed."))
```

- [ ] **Step 10: Run all shop tests, see pass**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_shop_contract
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_airport_shop
```

Expected: 12 + 7 tests OK.

- [ ] **Step 11: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airport_shops/doctype/rent_schedule airplane_mode/airport_shops/doctype/shop_contract \
  airplane_mode/airport_shops/doctype/airport_shop airplane_mode/airport_shops/doctype/tenant/tenant.json \
  airplane_mode/airport_shops/utils.py airplane_mode/airport_shops/tests/test_shop_contract.py
git commit -m "feat: shop contracts with rent schedule, overlap lock and shop status sync"
```

---

### Task 8: Rent Payment with partial payments and locks (Part 2.3)

**Files:**
- Create: `airplane_mode/airport_shops/doctype/rent_payment/{__init__.py,rent_payment.json,rent_payment.py,rent_payment.js}`
- Create: `airplane_mode/airport_shops/tests/test_rent_payment.py`

- [ ] **Step 1: Create Rent Payment**

`airplane_mode/airport_shops/doctype/rent_payment/__init__.py`: empty file.

`airplane_mode/airport_shops/doctype/rent_payment/rent_payment.json`:

```json
{
 "actions": [],
 "autoname": "RCPT-.YYYY.-.####",
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["shop_contract", "shop", "tenant", "tenant_email", "column_break_1", "period_start", "period_outstanding", "amount", "period_outstanding_after_payment", "details_section", "payment_date", "mode_of_payment", "column_break_2", "reference_no", "amended_from"],
 "fields": [
  {"fieldname": "shop_contract", "fieldtype": "Link", "label": "Shop Contract", "options": "Shop Contract", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "shop", "fieldtype": "Link", "label": "Shop", "options": "Airport Shop", "read_only": 1, "in_standard_filter": 1},
  {"fieldname": "tenant", "fieldtype": "Link", "label": "Tenant", "options": "Tenant", "read_only": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "tenant_email", "fieldtype": "Data", "label": "Tenant Email", "options": "Email", "read_only": 1},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "period_start", "fieldtype": "Date", "label": "Rent Period (start)", "reqd": 1, "in_list_view": 1},
  {"fieldname": "period_outstanding", "fieldtype": "Currency", "label": "Outstanding Before Payment", "read_only": 1},
  {"fieldname": "amount", "fieldtype": "Currency", "label": "Amount Paid", "reqd": 1, "in_list_view": 1},
  {"fieldname": "period_outstanding_after_payment", "fieldtype": "Currency", "label": "Outstanding After Payment", "read_only": 1, "no_copy": 1},
  {"fieldname": "details_section", "fieldtype": "Section Break", "label": "Payment Details"},
  {"fieldname": "payment_date", "fieldtype": "Date", "label": "Payment Date", "default": "Today", "reqd": 1},
  {"fieldname": "mode_of_payment", "fieldtype": "Select", "label": "Mode of Payment", "options": "Cash\nBank Transfer\nCard\nCheque", "default": "Cash", "reqd": 1},
  {"fieldname": "column_break_2", "fieldtype": "Column Break"},
  {"fieldname": "reference_no", "fieldtype": "Data", "label": "Reference No"},
  {"fieldname": "amended_from", "fieldtype": "Link", "label": "Amended From", "options": "Rent Payment", "no_copy": 1, "print_hide": 1, "read_only": 1, "search_index": 1}
 ],
 "is_submittable": 1,
 "links": [],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Rent Payment",
 "naming_rule": "Expression",
 "owner": "Administrator",
 "permissions": [
  {"amend": 1, "cancel": 1, "create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "submit": 1, "write": 1},
  {"amend": 1, "cancel": 1, "create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "Airport Authority Personnel", "share": 1, "submit": 1, "write": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": []
}
```

`airplane_mode/airport_shops/doctype/rent_payment/rent_payment.js`:

```javascript
frappe.ui.form.on("Rent Payment", {
	setup(frm) {
		frm.set_query("shop_contract", () => ({ filters: { docstatus: 1 } }));
	},
	onload(frm) {
		if (frm.is_new() && frm.doc.shop_contract && !frm.doc.period_start) {
			frm.trigger("shop_contract");
		}
	},
	shop_contract(frm) {
		if (!frm.doc.shop_contract) return;
		frappe
			.call({
				method: "airplane_mode.airport_shops.doctype.rent_payment.rent_payment.get_open_periods",
				args: { shop_contract: frm.doc.shop_contract },
			})
			.then((r) => {
				const periods = r.message || [];
				if (!periods.length) {
					frappe.msgprint(__("All rent periods of this contract are paid."));
					return;
				}
				frm.set_value("period_start", periods[0].period_start);
				frm.set_value("amount", periods[0].outstanding_amount);
			});
	},
});
```

- [ ] **Step 2: Sync**

```bash
cd /home/frappe-user/frappe-bench-dev && bench --site airplane.local migrate
```

- [ ] **Step 3: Write failing tests**

`airplane_mode/airport_shops/tests/test_rent_payment.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.doctype.rent_payment.rent_payment import get_open_periods
from airplane_mode.airport_shops.tests.factories import make_contract, make_payment, make_shop

FIRST = "2026-11-15"


def period(contract, period_start=FIRST):
	return frappe.db.get_value(
		"Rent Schedule",
		{"parent": contract.name, "period_start": period_start},
		["paid_amount", "outstanding_amount", "status"],
		as_dict=True,
	)


def totals(contract):
	return frappe.db.get_value("Shop Contract", contract.name, ["total_paid", "total_outstanding"], as_dict=True)


class TestRentPayment(FrappeTestCase):
	def setUp(self):
		self.contract = make_contract(make_shop(), start=FIRST, end="2027-02-14", rent=1000)

	def tearDown(self):
		frappe.db.rollback()

	def test_partial_then_full(self):
		first = make_payment(self.contract, FIRST, 400)
		self.assertEqual(period(self.contract).status, "Partly Paid")
		make_payment(self.contract, FIRST, 600)
		row = period(self.contract)
		self.assertEqual((row.status, row.paid_amount, row.outstanding_amount), ("Paid", 600 + 400, 0))
		self.assertEqual(totals(self.contract), {"total_paid": 1000, "total_outstanding": 2000})
		first.reload()
		self.assertEqual(first.period_outstanding_after_payment, 600)  # snapshot, not today's 0

	def test_overpayment_rejected(self):
		make_payment(self.contract, FIRST, 1000)
		with self.assertRaises(frappe.ValidationError):
			make_payment(self.contract, FIRST, 1)

	def test_draft_that_became_an_overpayment_cannot_be_submitted(self):
		draft = make_payment(self.contract, FIRST, 600, submit=False)  # valid when created
		make_payment(self.contract, FIRST, 600)  # someone else pays first
		with self.assertRaises(frappe.ValidationError):
			draft.submit()
		self.assertEqual(period(self.contract).paid_amount, 600)

	def test_cancel_reverts_period_and_totals(self):
		make_payment(self.contract, FIRST, 400)
		second = make_payment(self.contract, FIRST, 600)
		second.cancel()
		row = period(self.contract)
		self.assertEqual((row.status, row.paid_amount, row.outstanding_amount), ("Partly Paid", 400, 600))
		self.assertEqual(totals(self.contract).total_paid, 400)

	def test_precision_three_thirds_settle_exactly(self):
		for amount in (333.33, 333.33, 333.34):
			make_payment(self.contract, FIRST, amount)
		row = period(self.contract)
		self.assertEqual((row.status, row.outstanding_amount), ("Paid", 0))

	def test_unknown_period_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_payment(self.contract, "2026-11-20", 100)

	def test_cancelled_contract_rejected(self):
		contract = make_contract(make_shop(), start="2027-05-01", end="2027-06-30")
		contract.cancel()
		with self.assertRaises(frappe.ValidationError):
			make_payment(contract, "2027-05-01", 100)

	def test_contract_cancel_blocked_while_payments_exist(self):
		make_payment(self.contract, FIRST, 100)
		self.contract.reload()
		with self.assertRaises(frappe.ValidationError):
			self.contract.cancel()

	def test_fetches_contract_details(self):
		payment = make_payment(self.contract, FIRST, 100, submit=False)
		self.assertEqual(payment.tenant, self.contract.tenant)
		self.assertEqual(payment.shop, self.contract.shop)
		self.assertEqual(payment.period_outstanding, 1000)

	def test_open_periods_in_order(self):
		make_payment(self.contract, FIRST, 1000)
		periods = get_open_periods(self.contract.name)
		self.assertEqual([str(p.period_start) for p in periods], ["2026-12-15", "2027-01-15"])
```

- [ ] **Step 4: Run, see ImportError**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_rent_payment
```

- [ ] **Step 5: Implement the controller**

`airplane_mode/airport_shops/doctype/rent_payment/rent_payment.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from airplane_mode.airport_shops.utils import update_contract_totals


class RentPayment(Document):
	def validate(self):
		p = self.precision("amount") or 2
		if flt(self.amount, p) <= 0:
			frappe.throw(_("Amount Paid must be greater than zero."))

		contract = frappe.db.get_value(
			"Shop Contract", self.shop_contract, ["docstatus", "shop", "tenant", "tenant_email"], as_dict=True
		)
		if not contract or contract.docstatus != 1:
			frappe.throw(_("Shop Contract {0} is not submitted.").format(self.shop_contract))
		self.shop, self.tenant, self.tenant_email = contract.shop, contract.tenant, contract.tenant_email

		row = frappe.db.get_value(
			"Rent Schedule",
			{"parent": self.shop_contract, "parenttype": "Shop Contract", "period_start": self.period_start},
			["outstanding_amount"],
			as_dict=True,
		)
		if not row:
			frappe.throw(_("Contract {0} has no rent period starting on {1}.").format(self.shop_contract, self.period_start))
		self.period_outstanding = flt(row.outstanding_amount, p)
		# Early, friendly check. The authoritative check runs under a lock in on_submit.
		if flt(flt(self.amount) - flt(row.outstanding_amount), p) > 0:
			frappe.throw(_("Amount is more than the outstanding {0} for this period.").format(self.period_outstanding))

	def on_submit(self):
		p = self.precision("amount") or 2
		row = self._lock_period()
		new_paid = flt(flt(row.paid_amount) + flt(self.amount), p)
		if flt(new_paid - flt(row.amount), p) > 0:
			frappe.throw(_("This payment would overpay the period. Another payment was recorded first."))
		outstanding = self._apply(row, new_paid)
		self.db_set("period_outstanding_after_payment", outstanding)  # receipt snapshot

	def on_cancel(self):
		p = self.precision("amount") or 2
		row = self._lock_period()
		self._apply(row, max(flt(flt(row.paid_amount) - flt(self.amount), p), 0))

	def _lock_period(self):
		"""The only lock path for payments: contract row first, then the period row."""
		if not frappe.db.sql(
			"select name from `tabShop Contract` where name = %s and docstatus = 1 for update",
			self.shop_contract,
		):
			frappe.throw(_("Shop Contract {0} is not submitted.").format(self.shop_contract))
		rows = frappe.db.sql(
			"""select name, amount, paid_amount from `tabRent Schedule`
			where parent = %s and parenttype = 'Shop Contract' and period_start = %s
			for update""",
			(self.shop_contract, self.period_start),
			as_dict=True,
		)
		if not rows:
			frappe.throw(_("Contract {0} has no rent period starting on {1}.").format(self.shop_contract, self.period_start))
		return rows[0]

	def _apply(self, row, new_paid):
		p = self.precision("amount") or 2
		outstanding = max(flt(flt(row.amount) - new_paid, p), 0)
		if outstanding <= 0:
			status = "Paid"
		elif new_paid > 0:
			status = "Partly Paid"
		else:
			status = "Unpaid"
		frappe.db.set_value(
			"Rent Schedule",
			row.name,
			{"paid_amount": new_paid, "outstanding_amount": outstanding, "status": status},
			update_modified=False,
		)
		update_contract_totals(self.shop_contract)
		return outstanding


@frappe.whitelist()
def get_open_periods(shop_contract):
	frappe.has_permission("Shop Contract", "read", shop_contract, throw=True)
	return frappe.get_all(
		"Rent Schedule",
		filters={"parent": shop_contract, "parenttype": "Shop Contract", "status": ["!=", "Paid"]},
		fields=["period_start", "period_end", "outstanding_amount"],
		order_by="period_start asc",
	)
```

- [ ] **Step 6: Run, see pass**

Same command as Step 4. Expected: 10 tests OK.

- [ ] **Step 7: Manual concurrency check (two tabs)**

Create a contract with rent 1000. Open two **new Rent Payment** tabs for the same first period, each with amount 600, and submit both quickly. One succeeds. The other shows "This payment would overpay the period…" (or the validate message), and the row ends up Partly Paid with 600.

- [ ] **Step 8: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airport_shops/doctype/rent_payment airplane_mode/airport_shops/tests/test_rent_payment.py
git commit -m "feat: rent payments with partial amounts, row locks and receipt snapshot"
```

---

### Task 9: Scheduler jobs and rent reminders (Part 2.6)

**Files:**
- Create: `airplane_mode/airport_shops/tasks.py`
- Create: `airplane_mode/templates/emails/rent_reminder.html`, `airplane_mode/templates/emails/rent_overdue.html`
- Modify: `airplane_mode/hooks.py`
- Create: `airplane_mode/airport_shops/tests/test_reminders.py`

- [ ] **Step 1: Write the email templates**

`airplane_mode/templates/emails/rent_reminder.html`:

```html
<p>Dear {{ tenant_name }},</p>
<p>This is a friendly reminder that the rent for <b>{{ shop_name }}</b> ({{ shop }}) at {{ airport }}
for the period {{ period_start }} – {{ period_end }} is due on <b>{{ due_date }}</b>.</p>
<p>Amount outstanding: <b>{{ outstanding }}</b></p>
<p>Contract: {{ contract }}</p>
<p>Thank you,<br>Airport Authority</p>
```

`airplane_mode/templates/emails/rent_overdue.html`:

```html
<p>Dear {{ tenant_name }},</p>
<p>The rent for <b>{{ shop_name }}</b> ({{ shop }}) at {{ airport }} for the period
{{ period_start }} – {{ period_end }} was due on <b>{{ due_date }}</b> and is now overdue.</p>
<p>Amount outstanding: <b>{{ outstanding }}</b></p>
<p>Please pay as soon as possible. Contract: {{ contract }}</p>
<p>Airport Authority</p>
```

- [ ] **Step 2: Register the scheduler jobs** (append to `airplane_mode/hooks.py`)

```python
scheduler_events = {
	"daily": [
		"airplane_mode.airport_shops.tasks.sync_all_shop_statuses",
		"airplane_mode.airport_shops.tasks.send_rent_reminders",
	]
}
```

- [ ] **Step 3: Write failing tests**

`airplane_mode/airport_shops/tests/test_reminders.py`:

```python
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.tasks import send_rent_reminders
from airplane_mode.airport_shops.tests.factories import (
	ensure_outgoing_email_account,
	make_contract,
	make_payment,
	make_shop,
	make_tenant,
)

DUE = "2027-03-01"  # first period of the contract below


def row(contract, period_start=DUE):
	return frappe.db.get_value(
		"Rent Schedule",
		{"parent": contract.name, "period_start": period_start},
		["reminder_sent_on", "reminder_email", "overdue_reminder_sent_on", "overdue_reminder_email"],
		as_dict=True,
	)


class TestRentReminders(FrappeTestCase):
	def setUp(self):
		ensure_outgoing_email_account()
		settings = frappe.get_single("Airport Shop Settings")
		settings.update({"enable_rent_reminders": 1, "reminder_days_before": 3, "overdue_after_days": 3})
		settings.save()
		self.contract = make_contract(make_shop(), start=DUE, end="2027-05-31")

	def tearDown(self):
		frappe.db.rollback()

	def test_disabled_sends_nothing(self):
		frappe.db.set_single_value("Airport Shop Settings", "enable_rent_reminders", 0)
		self.assertEqual(send_rent_reminders(on_date="2027-02-27"), {"upcoming": 0, "overdue": 0})

	def test_upcoming_only_inside_window(self):
		self.assertEqual(send_rent_reminders(on_date="2027-02-25")["upcoming"], 0)  # 4 days before
		self.assertEqual(send_rent_reminders(on_date="2027-02-26")["upcoming"], 1)  # 3 days before
		r = row(self.contract)
		self.assertEqual(str(r.reminder_sent_on), "2027-02-26")
		self.assertTrue(frappe.db.exists("Email Queue", r.reminder_email))

	def test_upcoming_not_sent_twice(self):
		send_rent_reminders(on_date="2027-02-27")
		self.assertEqual(send_rent_reminders(on_date="2027-02-28")["upcoming"], 0)

	def test_no_upcoming_after_due_date(self):
		self.assertEqual(send_rent_reminders(on_date="2027-03-02")["upcoming"], 0)

	def test_overdue_sent_once_after_grace_days(self):
		self.assertEqual(send_rent_reminders(on_date="2027-03-03")["overdue"], 0)  # due + 2
		self.assertEqual(send_rent_reminders(on_date="2027-03-04")["overdue"], 1)  # due + 3
		self.assertEqual(send_rent_reminders(on_date="2027-03-05")["overdue"], 0)
		self.assertTrue(frappe.db.exists("Email Queue", row(self.contract).overdue_reminder_email))

	def test_paid_period_skipped(self):
		make_payment(self.contract, DUE, 1000)
		self.assertEqual(send_rent_reminders(on_date="2027-02-27")["upcoming"], 0)

	def test_failed_email_leaves_row_unflagged_and_others_continue(self):
		bad_tenant = make_tenant(email="broken@example.com")
		bad = make_contract(make_shop(), bad_tenant, start=DUE, end="2027-05-31")
		real_sendmail = frappe.sendmail
		errors_before = frappe.db.count("Error Log")

		def flaky(*args, **kwargs):
			if "broken@example.com" in kwargs.get("recipients", []):
				raise Exception("SMTP queue unavailable")
			return real_sendmail(*args, **kwargs)

		with patch("frappe.sendmail", side_effect=flaky):
			result = send_rent_reminders(on_date="2027-02-27")

		self.assertEqual(result["upcoming"], 1)
		self.assertIsNone(row(bad).reminder_sent_on)
		self.assertFalse(frappe.db.exists("Email Queue", {"reference_name": bad.name}))
		self.assertTrue(row(self.contract).reminder_sent_on)
		self.assertGreater(frappe.db.count("Error Log"), errors_before)

	def test_sendmail_returning_nothing_is_not_flagged(self):
		with patch("frappe.sendmail", return_value=[]):
			self.assertEqual(send_rent_reminders(on_date="2027-02-27")["upcoming"], 0)
		self.assertIsNone(row(self.contract).reminder_sent_on)
```

- [ ] **Step 4: Run, see ImportError**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_reminders
```

- [ ] **Step 5: Implement `tasks.py`**

`airplane_mode/airport_shops/tasks.py`:

```python
import frappe
from frappe import _
from frappe.utils import add_days, cint, fmt_money, formatdate, getdate, today

from airplane_mode.airport_shops.utils import sync_shop_status

REMINDER_KINDS = {
	"upcoming": {
		"flag": "reminder_sent_on",
		"link": "reminder_email",
		"template": "rent_reminder",
		"subject": "Rent due on {due_date}: {shop_name}",
	},
	"overdue": {
		"flag": "overdue_reminder_sent_on",
		"link": "overdue_reminder_email",
		"template": "rent_overdue",
		"subject": "Rent overdue since {due_date}: {shop_name}",
	},
}


class ReminderNotQueued(frappe.ValidationError):
	pass


def sync_all_shop_statuses(on_date=None):
	"""Daily: activate contracts that start today, release expired ones, switch back-to-back ones."""
	for shop in frappe.get_all("Airport Shop", pluck="name"):
		sync_shop_status(shop, on_date)


def send_rent_reminders(on_date=None):
	"""Daily: one upcoming and one overdue reminder per unpaid period, at most.

	Returns {"upcoming": n, "overdue": m} (rows actually queued). The scheduler commits at the end.
	"""
	result = {"upcoming": 0, "overdue": 0}
	settings = frappe.get_single("Airport Shop Settings")
	if not settings.enable_rent_reminders:
		return result

	day = getdate(on_date or today())
	windows = {
		# due_date - days_before <= day <= due_date
		"upcoming": ("rs.due_date between %(day)s and %(until)s", {"until": add_days(day, cint(settings.reminder_days_before))}),
		# day >= due_date + overdue_after_days
		"overdue": ("rs.due_date <= %(until)s", {"until": add_days(day, -max(cint(settings.overdue_after_days), 1))}),
	}
	for kind, (condition, values) in windows.items():
		for candidate in _candidates(REMINDER_KINDS[kind]["flag"], condition, {"day": day, **values}):
			if _send_one(candidate.name, candidate.contract, kind, day):
				result[kind] += 1
	return result


def _candidates(flag, condition, values):
	return frappe.db.sql(
		f"""select rs.name, rs.parent as contract
		from `tabRent Schedule` rs
		join `tabShop Contract` sc on sc.name = rs.parent
		where rs.parenttype = 'Shop Contract' and sc.docstatus = 1
			and rs.status != 'Paid' and rs.`{flag}` is null and {condition}
		order by rs.due_date, rs.name""",
		values,
		as_dict=True,
	)


def _send_one(row_name, contract, kind, day):
	"""Queue one reminder inside its own savepoint. True if it was queued and flagged."""
	spec = REMINDER_KINDS[kind]
	save_point = f"rent_reminder_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(save_point)
	try:
		locked = frappe.db.sql(
			f"""select `{spec['flag']}` as flag, status, period_start, period_end, due_date, outstanding_amount
			from `tabRent Schedule` where name = %s for update""",
			row_name,
			as_dict=True,
		)
		if not locked or locked[0].flag or locked[0].status == "Paid":
			return False  # another run got here first, or it was paid meanwhile
		row = locked[0]

		info = frappe.db.get_value("Shop Contract", contract, ["shop", "tenant", "tenant_email", "airport"], as_dict=True)
		args = {
			"tenant_name": frappe.db.get_value("Tenant", info.tenant, "tenant_name"),
			"shop": info.shop,
			"shop_name": frappe.db.get_value("Airport Shop", info.shop, "shop_name"),
			"airport": info.airport,
			"period_start": formatdate(row.period_start),
			"period_end": formatdate(row.period_end),
			"due_date": formatdate(row.due_date),
			"outstanding": fmt_money(row.outstanding_amount, currency=frappe.db.get_default("currency")),
			"contract": contract,
		}
		queued = frappe.sendmail(
			recipients=[info.tenant_email] if info.tenant_email else [],
			subject=spec["subject"].format(**args),
			template=spec["template"],
			args=args,
			reference_doctype="Shop Contract",
			reference_name=contract,
		)
		if not queued:
			# v15 returns [] when every recipient was filtered out (e.g. unsubscribed).
			raise ReminderNotQueued(_("No email was queued for {0}").format(info.tenant_email))

		frappe.db.set_value(
			"Rent Schedule", row_name, {spec["flag"]: day, spec["link"]: queued.name}, update_modified=False
		)
		return True
	except Exception:
		# Undo this row only: the flag and its Email Queue row go together or not at all.
		frappe.db.rollback(save_point=save_point)
		frappe.log_error(title=f"Rent reminder ({kind}) failed for {row_name}")
		return False
```

- [ ] **Step 6: Run, see pass**

Same command as Step 4. Expected: 8 tests OK. If a test errors with `OutgoingEmailError`, `ensure_outgoing_email_account()` didn't create the account. Check that Email Account insert succeeds with `frappe.flags.in_test` set (it skips the SMTP check).

- [ ] **Step 7: Reload hooks and check the scheduler sees the jobs**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local clear-cache
bench --site airplane.local execute frappe.utils.scheduler.get_scheduler_status 2>/dev/null || true
bench --site airplane.local execute frappe.client.get_list --kwargs '{"doctype": "Scheduled Job Type", "filters": {"method": ["like", "%airport_shops%"]}, "fields": ["method", "frequency"]}'
```

Expected: both methods are listed with frequency `Daily` (`migrate` or `clear-cache` creates them). If they're missing, run `bench --site airplane.local migrate`.

- [ ] **Step 8: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airport_shops/tasks.py airplane_mode/templates/emails airplane_mode/hooks.py \
  airplane_mode/airport_shops/tests/test_reminders.py
git commit -m "feat: daily shop status sync and once-per-period rent reminders"
```

---

### Task 10: Occupancy report, number cards, workspace (Part 2.4, 2.5)

**Files:**
- Create: `airplane_mode/airport_shops/report/__init__.py`
- Create: `airplane_mode/airport_shops/report/airport_shop_occupancy/{__init__.py,airport_shop_occupancy.json,airport_shop_occupancy.py,airport_shop_occupancy.js}`
- Create: `airplane_mode/airport_shops/tests/test_occupancy_report.py`
- Generated by the desk (export): `airplane_mode/airport_shops/number_card/...`, `airplane_mode/airport_shops/workspace/airport_shops/airport_shops.json`

- [ ] **Step 1: Write the failing report test**

`airplane_mode/airport_shops/tests/test_occupancy_report.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from airplane_mode.airport_shops.report.airport_shop_occupancy.airport_shop_occupancy import execute
from airplane_mode.airport_shops.tests.factories import make_airport, make_contract, make_shop


class TestOccupancyReport(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_counts_are_computed_live(self):
		airport = make_airport()
		occupied = make_shop(airport)
		make_shop(airport)
		make_contract(occupied, start=add_days(today(), -1), end=add_days(today(), 30))
		frappe.db.set_value("Airport", airport.name, "total_shops", 99)  # stored value is ignored

		columns, data, _message, chart = execute({"airport": airport.name})

		self.assertEqual(len(data), 1)
		self.assertEqual((data[0].total, data[0].available, data[0].occupied), (2, 1, 1))
		self.assertEqual(data[0].occupancy, 50.0)
		self.assertEqual(chart["type"], "bar")
```

- [ ] **Step 2: Create the report**

`airplane_mode/airport_shops/report/__init__.py` and `airplane_mode/airport_shops/report/airport_shop_occupancy/__init__.py`: empty files.

`airplane_mode/airport_shops/report/airport_shop_occupancy/airport_shop_occupancy.json`:

```json
{
 "add_total_row": 1,
 "columns": [],
 "creation": "2026-11-10 12:00:00.000000",
 "disabled": 0,
 "docstatus": 0,
 "doctype": "Report",
 "filters": [],
 "idx": 0,
 "is_standard": "Yes",
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Airport Shop Occupancy",
 "owner": "Administrator",
 "prepared_report": 0,
 "ref_doctype": "Airport Shop",
 "report_name": "Airport Shop Occupancy",
 "report_type": "Script Report",
 "roles": [{"role": "System Manager"}, {"role": "Airport Authority Personnel"}]
}
```

`airplane_mode/airport_shops/report/airport_shop_occupancy/airport_shop_occupancy.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"fieldname": "airport", "label": _("Airport"), "fieldtype": "Link", "options": "Airport", "width": 220},
		{"fieldname": "total", "label": _("Total Shops"), "fieldtype": "Int", "width": 120},
		{"fieldname": "available", "label": _("Available"), "fieldtype": "Int", "width": 120},
		{"fieldname": "occupied", "label": _("Occupied"), "fieldtype": "Int", "width": 120},
		{"fieldname": "occupancy", "label": _("Occupancy %"), "fieldtype": "Percent", "width": 120},
	]

	condition = "where airport = %(airport)s" if filters.get("airport") else ""
	# Always computed live from the shops; never reads the stored counts on Airport.
	data = frappe.db.sql(
		f"""select airport,
			count(*) as total,
			sum(status = 'Available') as available,
			sum(status = 'Occupied') as occupied
		from `tabAirport Shop` {condition}
		group by airport order by airport""",
		filters,
		as_dict=True,
	)
	for row in data:
		row.available, row.occupied = int(row.available or 0), int(row.occupied or 0)
		row.occupancy = flt(row.occupied * 100 / row.total, 1) if row.total else 0

	chart = {
		"data": {
			"labels": [row.airport for row in data],
			"datasets": [
				{"name": _("Available"), "values": [row.available for row in data]},
				{"name": _("Occupied"), "values": [row.occupied for row in data]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
	}
	return columns, data, None, chart
```

`airplane_mode/airport_shops/report/airport_shop_occupancy/airport_shop_occupancy.js`:

```javascript
frappe.query_reports["Airport Shop Occupancy"] = {
	filters: [{ fieldname: "airport", label: __("Airport"), fieldtype: "Link", options: "Airport" }],
};
```

- [ ] **Step 3: Sync, run the test**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local migrate
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_occupancy_report
```

Expected: 1 test OK. Open `/app/query-report/Airport Shop Occupancy` and check the bar chart and table.

- [ ] **Step 4: Create the number cards in the desk (exported automatically in developer mode)**

In `/app/number-card/new`, create these two cards. For both: **Is Standard** ✔, **Module** = Airport Shops, **Type** = Document Type, **Document Type** = Airport Shop, **Function** = Count.
1. Label **Available Shops**, Filters: `status = Available`
2. Label **Occupied Shops**, Filters: `status = Occupied`

- [ ] **Step 5: Create the workspace in the desk**

Open `/app/airport-shops` (or **+ New Workspace**) and create a public workspace **Airport Shops** with module **Airport Shops**. Add:
- Number cards: Available Shops, Occupied Shops
- Shortcuts: Airport Shop, Shop Contract, Rent Payment, Tenant, Shop Lead (after Task 12), Airport Shop Settings, Airport Shop Occupancy (report)

Save. Then check the exported files:

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
ls airplane_mode/airport_shops/number_card airplane_mode/airport_shops/workspace/airport_shops
```

Expected: `available_shops/`, `occupied_shops/` and `airport_shops.json`.

- [ ] **Step 6: Commit**

```bash
git add airplane_mode/airport_shops/report airplane_mode/airport_shops/number_card airplane_mode/airport_shops/workspace \
  airplane_mode/airport_shops/tests/test_occupancy_report.py
git commit -m "feat: airport shop occupancy report, number cards and workspace"
```

---

### Task 11: Rent receipt print format (Part 2.3, Print Designer)

**Files:**
- Generated by the desk (export): `airplane_mode/airport_shops/print_format/rent_receipt/rent_receipt.json`

- [ ] **Step 1: Design the receipt in Print Designer**

Open **Print Designer** → **New** → DocType **Rent Payment**, name **Rent Receipt**. Lay out:
- Header: "Rent Receipt", the receipt number (`name`) and `payment_date`
- Tenant block: `tenant`, `tenant_email`
- Shop block: `shop`, `shop_contract`; pull `airport` through the shop link if the designer offers linked fields, otherwise show `shop`
- Payment table: Period (`period_start`), Amount Paid (`amount`), Outstanding After Payment (`period_outstanding_after_payment`), Mode (`mode_of_payment`), Reference (`reference_no`)
- Footer: "Received with thanks — Airport Authority"

Save it.

- [ ] **Step 2: Make it standard so it ships with the app**

Open `/app/print-format/Rent Receipt`, set **Standard** = Yes and **Module** = Airport Shops, then save. Check the export:

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
ls airplane_mode/airport_shops/print_format/rent_receipt/
```

Expected: `rent_receipt.json`.

- [ ] **Step 3 (only if Print Designer could not be installed): Jinja fallback**

Create `/app/print-format/new` with Name **Rent Receipt**, DocType **Rent Payment**, Module **Airport Shops**, Standard **Yes**, Custom Format ✔, Print Format Type **Jinja**, and this HTML:

```html
<div style="font-family: sans-serif; max-width: 640px; margin: auto;">
  <h2 style="margin-bottom: 0;">Rent Receipt</h2>
  <p style="color:#666;margin-top:4px;">{{ doc.name }} · {{ frappe.utils.formatdate(doc.payment_date) }}</p>
  <table style="width:100%; border-collapse: collapse; margin-top: 16px;">
    <tr><td><b>Tenant</b></td><td>{{ frappe.db.get_value("Tenant", doc.tenant, "tenant_name") }} ({{ doc.tenant_email }})</td></tr>
    <tr><td><b>Shop</b></td><td>{{ frappe.db.get_value("Airport Shop", doc.shop, "shop_name") }} ({{ doc.shop }})</td></tr>
    <tr><td><b>Contract</b></td><td>{{ doc.shop_contract }}</td></tr>
    <tr><td><b>Period starting</b></td><td>{{ frappe.utils.formatdate(doc.period_start) }}</td></tr>
    <tr><td><b>Amount paid</b></td><td>{{ doc.get_formatted("amount") }}</td></tr>
    <tr><td><b>Outstanding after this payment</b></td><td>{{ doc.get_formatted("period_outstanding_after_payment") }}</td></tr>
    <tr><td><b>Mode</b></td><td>{{ doc.mode_of_payment }} {{ doc.reference_no or "" }}</td></tr>
  </table>
  <p style="margin-top: 32px;">Received with thanks — Airport Authority</p>
</div>
```

- [ ] **Step 4: Manual check**

Submit a 400 payment and then a 600 payment on one period. Print the first payment: it shows **Outstanding After Payment = 600**, not 0.

- [ ] **Step 5: Commit**

```bash
git add airplane_mode/airport_shops/print_format
git commit -m "feat: rent receipt print format"
```

---

### Task 12: Web portal + Shop Lead web form (Part 2 Web Portal)

**Files:**
- Create: `airplane_mode/airport_shops/doctype/shop_lead/{__init__.py,shop_lead.json,shop_lead.py}`
- Create: `airplane_mode/airport_shops/web_form/__init__.py`, `airplane_mode/airport_shops/web_form/shop_lead/{__init__.py,shop_lead.json,shop_lead.py,shop_lead.js}`
- Create: `airplane_mode/airport_shops/portal.py`
- Create: `airplane_mode/templates/shop_portal_base.html`, `airplane_mode/public/css/shop_portal.css`
- Create: `airplane_mode/www/shops/{__init__.py,index.html,index.py,shop.html,shop.py}`
- Modify: `airplane_mode/hooks.py`
- Create: `airplane_mode/airport_shops/tests/test_portal.py`

- [ ] **Step 1: Create Shop Lead**

`airplane_mode/airport_shops/doctype/shop_lead/__init__.py`: empty file.

`airplane_mode/airport_shops/doctype/shop_lead/shop_lead.json`:

```json
{
 "actions": [],
 "autoname": "LEAD-.####",
 "creation": "2026-11-10 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["lead_name", "email", "phone", "column_break_1", "shop", "status", "message_section", "message"],
 "fields": [
  {"fieldname": "lead_name", "fieldtype": "Data", "label": "Your Name", "reqd": 1, "in_list_view": 1},
  {"fieldname": "email", "fieldtype": "Data", "label": "Email", "options": "Email", "reqd": 1, "in_list_view": 1},
  {"fieldname": "phone", "fieldtype": "Data", "label": "Phone", "options": "Phone"},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "shop", "fieldtype": "Link", "label": "Shop", "options": "Airport Shop", "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "New\nContacted\nConverted\nLost", "default": "New", "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "message_section", "fieldtype": "Section Break"},
  {"fieldname": "message", "fieldtype": "Small Text", "label": "Message"}
 ],
 "links": [],
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "Shop Lead",
 "naming_rule": "Expression",
 "owner": "Administrator",
 "permissions": [
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1},
  {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "Airport Authority Personnel", "share": 1, "write": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "title_field": "lead_name"
}
```

`airplane_mode/airport_shops/doctype/shop_lead/shop_lead.py`:

```python
# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ShopLead(Document):
	def before_insert(self):
		self.status = "New"  # web visitors can't pick their own status
```

- [ ] **Step 2: Create the web form**

`airplane_mode/airport_shops/web_form/__init__.py` and `airplane_mode/airport_shops/web_form/shop_lead/__init__.py`: empty files.

`airplane_mode/airport_shops/web_form/shop_lead/shop_lead.json`:

```json
{
 "allow_comments": 0,
 "allow_delete": 0,
 "allow_edit": 0,
 "allow_incomplete": 0,
 "allow_multiple": 1,
 "allow_print": 0,
 "anonymous": 0,
 "apply_document_permissions": 0,
 "button_label": "Send",
 "condition_json": "[]",
 "creation": "2026-11-10 12:00:00.000000",
 "doc_type": "Shop Lead",
 "docstatus": 0,
 "doctype": "Web Form",
 "idx": 0,
 "introduction_text": "<p>Interested in renting this shop? Leave your details and our team will contact you.</p>",
 "is_standard": 1,
 "list_columns": [],
 "login_required": 0,
 "max_attachment_size": 0,
 "modified": "2026-11-10 12:00:00.000000",
 "modified_by": "Administrator",
 "module": "Airport Shops",
 "name": "shop-lead",
 "owner": "Administrator",
 "published": 1,
 "route": "shop-lead",
 "show_attachments": 0,
 "show_list": 0,
 "show_sidebar": 0,
 "success_message": "Thanks! Our leasing team will get back to you soon.",
 "success_title": "Request received",
 "success_url": "/shops",
 "title": "Rent a Shop",
 "web_form_fields": [
  {"fieldname": "lead_name", "fieldtype": "Data", "label": "Your Name", "reqd": 1},
  {"fieldname": "email", "fieldtype": "Data", "label": "Email", "options": "Email", "reqd": 1},
  {"fieldname": "phone", "fieldtype": "Data", "label": "Phone", "options": "Phone"},
  {"fieldname": "shop", "fieldtype": "Link", "label": "Shop", "options": "Airport Shop", "allow_read_on_all_link_options": 1},
  {"fieldname": "message", "fieldtype": "Small Text", "label": "Message"}
 ]
}
```

`airplane_mode/airport_shops/web_form/shop_lead/shop_lead.py`:

```python
def get_context(context):
	pass
```

`airplane_mode/airport_shops/web_form/shop_lead/shop_lead.js`:

```javascript
frappe.ready(function () {
	// /shop-lead/new?shop=CAI-A12 pre-fills the shop the visitor came from.
	const shop = frappe.utils.get_query_params().shop;
	if (!shop) return;
	frappe.web_form.after_load = () => frappe.web_form.set_value("shop", shop);
	if (frappe.web_form.fields_dict && frappe.web_form.fields_dict.shop) {
		frappe.web_form.set_value("shop", shop);
	}
});
```

- [ ] **Step 3: Write failing portal tests**

`airplane_mode/airport_shops/tests/test_portal.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from airplane_mode.airport_shops.portal import PUBLIC_FIELDS, get_public_shop, get_public_shops
from airplane_mode.airport_shops.tests.factories import make_contract, make_shop, make_tenant


class TestPortal(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_list_only_published_shops_with_public_fields(self):
		visible = make_shop()
		hidden = make_shop(published=0)
		names = [s.name for s in get_public_shops()]
		self.assertIn(visible.name, names)
		self.assertNotIn(hidden.name, names)
		shop = next(s for s in get_public_shops() if s.name == visible.name)
		self.assertFalse({"current_tenant", "current_contract", "contract_expiry"} & set(shop))

	def test_detail_hides_unpublished(self):
		self.assertIsNone(get_public_shop(make_shop(published=0).name))
		self.assertIsNone(get_public_shop("does-not-exist"))

	def test_rendered_pages_use_picnic_and_do_not_leak_tenant(self):
		from frappe.website.serve import get_response_content

		tenant = make_tenant()
		shop = make_shop()
		contract = make_contract(shop, tenant, start=add_days(today(), -1), end=add_days(today(), 30))
		frappe.set_user("Guest")
		for path in ("shops", f"shops/{shop.name}"):
			content = get_response_content(path)
			self.assertIn(shop.shop_name, content)
			self.assertIn("picnic.min.css", content)  # our own base template, not web.html
			self.assertNotIn(tenant.tenant_name, content)
			self.assertNotIn(contract.name, content)

	def test_public_fields_never_include_tenant_data(self):
		self.assertFalse({"current_tenant", "current_contract", "contract_expiry"} & set(PUBLIC_FIELDS))
```

- [ ] **Step 4: Run, see ImportError**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local migrate
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_portal
```

- [ ] **Step 5: Implement `portal.py`**

`airplane_mode/airport_shops/portal.py`:

```python
"""Public (Guest) queries for the shop website.

frappe.get_all ignores permissions, so permlevel doesn't protect anything here. Only the
fields listed below ever reach a template.
"""
import frappe
from frappe.utils import fmt_money

PUBLIC_FIELDS = [
	"name",
	"shop_name",
	"shop_number",
	"airport",
	"shop_type",
	"area",
	"rent_amount",
	"status",
	"image",
	"description",
]


def _decorate(shop):
	shop.rent_display = fmt_money(shop.rent_amount, currency=frappe.db.get_default("currency"))
	return shop


def get_public_shops(airport=None):
	filters = {"published": 1}
	if airport:
		filters["airport"] = airport
	shops = frappe.get_all("Airport Shop", filters=filters, fields=PUBLIC_FIELDS, order_by="airport asc, shop_number asc")
	return [_decorate(shop) for shop in shops]


def get_public_shop(name):
	if not name:
		return None
	rows = frappe.get_all("Airport Shop", filters={"name": name, "published": 1}, fields=PUBLIC_FIELDS, limit=1)
	return _decorate(rows[0]) if rows else None


def get_public_airports():
	return frappe.get_all("Airport Shop", filters={"published": 1}, pluck="airport", distinct=True, order_by="airport asc")
```

- [ ] **Step 6: Base template and CSS (does not extend `web.html`)**

`airplane_mode/templates/shop_portal_base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title>{% block title %}Airport Shops{% endblock %}</title>
	<link rel="stylesheet" href="/assets/airplane_mode/css/picnic.min.css">
	<link rel="stylesheet" href="/assets/airplane_mode/css/shop_portal.css">
</head>
<body>
	<nav>
		<a href="/shops" class="brand"><span>✈ Airport Shops</span></a>
		<input id="menu" type="checkbox" class="show">
		<label for="menu" class="burger pseudo button">☰</label>
		<div class="menu">
			<a href="/shops" class="pseudo button">All shops</a>
			<a href="/shop-lead/new" class="button">Rent a shop</a>
		</div>
	</nav>
	<main class="portal">
		{% block content %}{% endblock %}
	</main>
</body>
</html>
```

`airplane_mode/public/css/shop_portal.css`:

```css
.portal { max-width: 1040px; margin: 5em auto 3em; padding: 0 1em; }
.portal .card img { width: 100%; height: 180px; object-fit: cover; }
.portal .card header h3 { margin: 0; }
.portal .meta { color: #666; font-size: .9em; }
.portal .filters { margin-bottom: 1.5em; max-width: 360px; }
.portal .detail img { max-width: 100%; border-radius: .2em; }
```

- [ ] **Step 7: List page**

`airplane_mode/www/shops/__init__.py`: empty file.

`airplane_mode/www/shops/index.py`:

```python
import frappe

from airplane_mode.airport_shops.portal import get_public_airports, get_public_shops

no_cache = 1


def get_context(context):
	airport = frappe.form_dict.get("airport") or None
	context.selected_airport = airport
	context.airports = get_public_airports()
	context.shops = get_public_shops(airport)
	return context
```

`airplane_mode/www/shops/index.html`:

```html
{% extends "templates/shop_portal_base.html" %}
{% block title %}Shops for lease{% endblock %}
{% block content %}
<h1>Shops at our airports</h1>

<form method="get" class="filters">
	<select name="airport" onchange="this.form.submit()">
		<option value="">All airports</option>
		{% for airport in airports %}
		<option value="{{ airport | e }}" {% if airport == selected_airport %}selected{% endif %}>{{ airport | e }}</option>
		{% endfor %}
	</select>
</form>

<div class="flex one two-600 three-900">
	{% for shop in shops %}
	<div>
		<article class="card">
			{% if shop.image %}<img src="{{ shop.image | e }}" alt="{{ shop.shop_name | e }}">{% endif %}
			<header>
				<h3><a href="/shops/{{ shop.name | urlencode }}">{{ shop.shop_name | e }}</a></h3>
				<span class="label {{ 'success' if shop.status == 'Available' else 'error' }}">{{ shop.status }}</span>
			</header>
			<footer class="meta">
				Shop {{ shop.shop_number | e }} · {{ shop.airport | e }}<br>
				{{ (shop.shop_type or "") | e }} · {{ shop.area or 0 }} sq ft · {{ shop.rent_display }} / month
			</footer>
		</article>
	</div>
	{% else %}
	<p>No shops are listed right now.</p>
	{% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 8: Detail page + route rule**

`airplane_mode/www/shops/shop.py`:

```python
from urllib.parse import quote

import frappe

from airplane_mode.airport_shops.portal import get_public_shop

no_cache = 1


def get_context(context):
	shop = get_public_shop(frappe.form_dict.get("shop"))
	if not shop:
		raise frappe.DoesNotExistError
	context.shop = shop
	context.lead_url = f"/shop-lead/new?shop={quote(shop.name)}"
	return context
```

`airplane_mode/www/shops/shop.html`:

```html
{% extends "templates/shop_portal_base.html" %}
{% block title %}{{ shop.shop_name | e }}{% endblock %}
{% block content %}
<p><a href="/shops">← All shops</a></p>
<article class="detail">
	<h1>{{ shop.shop_name | e }}
		<span class="label {{ 'success' if shop.status == 'Available' else 'error' }}">{{ shop.status }}</span>
	</h1>
	{% if shop.image %}<img src="{{ shop.image | e }}" alt="{{ shop.shop_name | e }}">{% endif %}
	<table class="primary">
		<tr><th>Shop number</th><td>{{ shop.shop_number | e }}</td></tr>
		<tr><th>Airport</th><td>{{ shop.airport | e }}</td></tr>
		<tr><th>Type</th><td>{{ (shop.shop_type or "—") | e }}</td></tr>
		<tr><th>Area</th><td>{{ shop.area or 0 }} sq ft</td></tr>
		<tr><th>Rent</th><td>{{ shop.rent_display }} / month</td></tr>
	</table>
	{% if shop.description %}<div>{{ shop.description }}</div>{% endif %}

	{% if shop.status == "Available" %}
	<p><a class="button" href="{{ lead_url }}">Interested? Apply to rent this shop</a></p>
	{% else %}
	<p class="meta">This shop is currently leased. <a href="{{ lead_url }}">Join the waiting list</a>.</p>
	{% endif %}
</article>
{% endblock %}
```

Append to `airplane_mode/hooks.py`:

```python
website_route_rules = [
	{"from_route": "/shops/<shop>", "to_route": "shops/shop"},
]
```

- [ ] **Step 9: Sync, run tests**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local migrate
bench --site airplane.local clear-cache
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_portal
```

Expected: 4 tests OK (`frappe.website.serve.get_response_content` exists in v15.125.0).

- [ ] **Step 10: Manual check**

```bash
curl -s http://localhost:8001/shops | grep -c "picnic.min.css"     # expect 1
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/shops/NOPE   # expect 404
```

In a private browser window, open `/shops`, click a shop, click **Interested? Apply to rent**, and check that the form opens with Shop pre-filled. Submit it, then confirm a new Shop Lead appears in the desk.

- [ ] **Step 11: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airport_shops/doctype/shop_lead airplane_mode/airport_shops/web_form airplane_mode/airport_shops/portal.py \
  airplane_mode/templates/shop_portal_base.html airplane_mode/public/css/shop_portal.css airplane_mode/www/shops \
  airplane_mode/hooks.py airplane_mode/airport_shops/tests/test_portal.py
git commit -m "feat: shop portal pages and shop lead web form"
```

---

### Task 13: Field-level permissions test + Bruno REST collection (Part 3)

**Files:**
- Create: `airplane_mode/airport_shops/tests/test_permissions.py`
- Create: `bruno/airplane_mode/bruno.json`, `bruno/airplane_mode/environments/local.bru`
- Create: `bruno/airplane_mode/List Shops (all fields).bru`, `bruno/airplane_mode/List Shops (public fields).bru`, `bruno/airplane_mode/Create Shop.bru`
- Modify: `.gitignore`

- [ ] **Step 1: Write the permission test**

`airplane_mode/airport_shops/tests/test_permissions.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from airplane_mode.airport_shops.tests.factories import make_contract, make_shop, unique


def make_user(role):
	email = f"{unique('api')}@example.com"
	frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": "API", "send_welcome_email": 0, "roles": [{"role": role}]}
	).insert(ignore_permissions=True)
	return email


class TestShopFieldPermissions(FrappeTestCase):
	def setUp(self):
		self.shop = make_shop()
		make_contract(self.shop, start=add_days(today(), -1), end=add_days(today(), 30))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _row_as(self, role):
		frappe.set_user(make_user(role))
		rows = frappe.get_list("Airport Shop", fields=["*"], filters={"name": self.shop.name})
		frappe.set_user("Administrator")
		return rows[0]

	def test_travel_agent_does_not_see_tenant_fields(self):
		row = self._row_as("Travel Agent")
		self.assertIn("status", row)
		self.assertNotIn("current_tenant", row)
		self.assertNotIn("current_contract", row)

	def test_airport_authority_sees_tenant_fields(self):
		row = self._row_as("Airport Authority Personnel")
		self.assertTrue(row.get("current_tenant"))
```

- [ ] **Step 2: Run**

```bash
cd /home/frappe-user/frappe-bench-dev
bench --site airplane.local run-tests --module airplane_mode.airport_shops.tests.test_permissions
```

Expected: 2 tests OK. The permissions were already defined in Task 5. If the Travel Agent test fails, check that `airport_shop.json` has permlevel 1 rows only for System Manager and Airport Authority Personnel.

- [ ] **Step 3: Write the Bruno collection**

`bruno/airplane_mode/bruno.json`:

```json
{
  "version": "1",
  "name": "Airplane Mode",
  "type": "collection",
  "ignore": ["node_modules", ".git"]
}
```

`bruno/airplane_mode/environments/local.bru` (key and secret are **secret** vars: Bruno stores their values on your machine, not in this file):

```
vars {
  base_url: http://localhost:8001
}
vars:secret [
  api_key,
  api_secret
]
```

`bruno/airplane_mode/List Shops (all fields).bru`:

```
meta {
  name: List Shops (all fields)
  type: http
  seq: 1
}

get {
  url: {{base_url}}/api/resource/Airport Shop?fields=["*"]&limit_page_length=0
  body: none
  auth: none
}

params:query {
  fields: ["*"]
  limit_page_length: 0
}

headers {
  Authorization: token {{api_key}}:{{api_secret}}
}
```

`bruno/airplane_mode/List Shops (public fields).bru`:

```
meta {
  name: List Shops (public fields)
  type: http
  seq: 2
}

get {
  url: {{base_url}}/api/resource/Airport Shop?fields=["name","shop_name","shop_number","airport","shop_type","area","rent_amount","status"]&limit_page_length=0
  body: none
  auth: none
}

params:query {
  fields: ["name","shop_name","shop_number","airport","shop_type","area","rent_amount","status"]
  limit_page_length: 0
}

headers {
  Authorization: token {{api_key}}:{{api_secret}}
}
```

`bruno/airplane_mode/Create Shop.bru` (set `airport` to an Airport name that exists on your site):

```
meta {
  name: Create Shop
  type: http
  seq: 3
}

post {
  url: {{base_url}}/api/resource/Airport Shop
  body: json
  auth: none
}

headers {
  Authorization: token {{api_key}}:{{api_secret}}
  Content-Type: application/json
}

body:json {
  {
    "shop_number": "API-1",
    "shop_name": "Coffee Corner (created via API)",
    "airport": "Cairo International Airport",
    "shop_type": "Stall",
    "area": 80,
    "status": "Occupied"
  }
}
```

The `"status": "Occupied"` line is there on purpose. The response shows `"status": "Available"`, which demonstrates that clients can't set the status.

Add to `.gitignore` (create the file if it doesn't exist):

```
bruno/**/.env
```

- [ ] **Step 4: Generate API keys and try it**

1. In the desk, create a user **api.authority@example.com** with role **Airport Authority Personnel**. Open the user → **Settings** → **API Access** → **Generate Keys**, and copy the secret (it is shown once).
2. In Bruno: **Open Collection** → `bruno/airplane_mode`, select environment **local**, and paste the key and secret into `api_key` / `api_secret`.
3. Run **List Shops (all fields)** → 200, and rows include `current_tenant`.
4. Run **Create Shop** → 200, and `data.status` is `Available`.
5. Make a second user with only the **Travel Agent** role, generate keys for it, and run **List Shops (all fields)** with those keys → no `current_tenant` / `current_contract` in the rows.
6. Remove the Authorization header and run again → 403. This shows the call is authenticated.

- [ ] **Step 5: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add airplane_mode/airport_shops/tests/test_permissions.py bruno .gitignore
git commit -m "feat: field-level shop permissions test and bruno REST collection"
```

---

### Task 14: Full verification, spec touch-up, demo checklist, packaging

**Files:**
- Modify: `docs/superpowers/specs/2026-11-10-assignment-4-design.md`
- Create: `docs/superpowers/demo-checklist.md`

- [ ] **Step 1: Run every test module**

```bash
cd /home/frappe-user/frappe-bench-dev
for m in airplane_mode.airplane_mode.tests.test_crew_and_gate \
         airplane_mode.airport_shops.tests.test_settings \
         airplane_mode.airport_shops.tests.test_airport_shop \
         airplane_mode.airport_shops.tests.test_rent_schedule \
         airplane_mode.airport_shops.tests.test_shop_contract \
         airplane_mode.airport_shops.tests.test_rent_payment \
         airplane_mode.airport_shops.tests.test_reminders \
         airplane_mode.airport_shops.tests.test_occupancy_report \
         airplane_mode.airport_shops.tests.test_portal \
         airplane_mode.airport_shops.tests.test_permissions; do
  bench --site airplane.local run-tests --module "$m" || echo "FAILED: $m"
done
```

Expected: no `FAILED:` lines.

- [ ] **Step 2: Fresh-install check (the grader installs the app from the zip)**

```bash
cd /home/frappe-user/frappe-bench-dev
bench new-site verify.local --admin-password admin --db-root-password <your-mariadb-root-password> --install-app airplane_mode
bench --site verify.local execute frappe.client.get_list --kwargs '{"doctype": "Shop Type", "fields": ["name", "enabled"]}'
bench drop-site verify.local --db-root-password <your-mariadb-root-password> --force
```

Expected: install succeeds, and the three shop types are listed. Ask the user for the MariaDB root password, and don't guess it.

- [ ] **Step 3: Touch up the spec to match what was built**

In `docs/superpowers/specs/2026-11-10-assignment-4-design.md`:
- Replace "where the full period is `period_start` to `period_start + 1 month − 1 day`" with "where the full period runs from `period_start` to the day before the next anniversary".
- Replace "(`FrappeTestCase.freeze_time`)" with "(date-dependent functions take `on_date`; `freezegun` is not installed in this bench)".
- Replace "called by `sync_shop_status` and by Airport Shop `on_trash`" with "called by `sync_shop_status` and by Airport Shop `after_delete`".
- Under Setup Prerequisites add: "An outgoing Email Account (default outgoing) so reminders can be queued and delivered."

- [ ] **Step 4: Write the demo checklist (in assignment order, for the video)**

`docs/superpowers/demo-checklist.md`:

```markdown
# Day 4 demo checklist

## Part 1
- [ ] Flight form → Crew table: add Pilot + Cabin Crew; adding the same person twice is refused.
- [ ] Ticket shows Gate Number from its flight.
- [ ] Change gate on a submitted flight → Update → RQ Job list shows the job → ticket shows new gate.

## Part 2
- [ ] Module "Airport Shops" in the sidebar / workspace.
- [ ] Airport Shop form: number, name, airport, type, area, rent; status/tenant are read-only.
- [ ] Tenant form (name, email, phone, company).
- [ ] Shop Contract: dates + rent → submit → Rent Schedule generated (show a stub period being prorated).
- [ ] Shop becomes Occupied; Airport form shows Total / Available / Occupied.
- [ ] Rent Payment: partial 400 then 600 → statuses; print the receipt (Print Designer) for the first one.
- [ ] Occupancy report with chart; number cards on the workspace.
- [ ] Airport Shop Settings: default rent (new shop picks it up), enable reminders, Send Reminders Now → Email Queue entries.
- [ ] Scheduled Job Type list: the two daily jobs.
- [ ] Background job for gate change (already shown in Part 1).
- [ ] Payment schedule explanation: anniversary periods, proration, partial payments, overpay blocked.

## Web portal
- [ ] /shops list (Picnic styling, not web.html) → shop detail → "Apply to rent" → web form pre-filled → Shop Lead in desk.

## Part 3
- [ ] Shop Type list: Stall, Walk-through, Normal shipped by fixtures; disabling one hides it in the shop form.
- [ ] Bruno: List Shops (all fields), Create Shop; show the `Authorization: token key:secret` header and the 403 without it.
```

- [ ] **Step 5: Commit**

```bash
cd /home/frappe-user/frappe-bench-dev/apps/airplane_mode
git add docs/superpowers/specs/2026-11-10-assignment-4-design.md docs/superpowers/demo-checklist.md
git commit -m "docs: align spec with implementation and add demo checklist"
```

- [ ] **Step 6: Package the app for submission**

```bash
cd /home/frappe-user/frappe-bench-dev/apps
zip -r ~/airplane_mode.zip airplane_mode -x "*/__pycache__/*" "*/.git/*" "*/node_modules/*" "*.pyc"
ls -lh ~/airplane_mode.zip
```

Expected: the zip exists and is a few MB at most.

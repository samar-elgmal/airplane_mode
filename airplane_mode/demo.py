"""Demo data for the Assignment 4 walkthrough (see docs/superpowers/scenarios.md).

    bench --site airplane.local execute airplane_mode.demo.seed
    bench --site airplane.local execute airplane_mode.demo.clear

Everything it makes is marked "Demo" and uses @example.com emails. It never turns on rent
reminders and never sends email. Cases that must be refused are attempted and their error
message is printed. The case numbers match scenarios.md.
"""

import frappe
from frappe.utils import add_days, add_months, getdate, today

from airplane_mode.airplane_mode.tasks import update_ticket_gate_numbers
from airplane_mode.airport_shops.doctype.shop_lead.shop_lead import create_tenant
from airplane_mode.airport_shops.utils import sync_shop_status

MARK = "Demo"
NORTH, SOUTH = "Demo Airport North", "Demo Airport South"


def log(case, text):
	print(f"  [{case}] {text}")


def refused(case, text, fn):
	"""Run something that must fail, roll back just that attempt, and print the message."""
	frappe.db.savepoint("demo_refused")
	try:
		fn()
	except frappe.ValidationError as e:
		frappe.db.rollback(save_point="demo_refused")
		frappe.clear_messages()
		log(case, f"refused as expected: {text} -> {frappe.utils.strip_html(str(e))[:110]}")
		return
	frappe.db.rollback(save_point="demo_refused")
	raise Exception(f"[{case}] {text} was NOT refused")


def seed():
	if frappe.db.exists("Airport", NORTH):
		print("Demo data already exists. Run airplane_mode.demo.clear first.")
		return
	frappe.flags.mute_emails = True
	print("Part 1 - crew and gate")
	seed_flights()
	print("Part 2 - shops, contracts, payments")
	shops, tenants = seed_shops()
	leads = seed_leads(shops)
	contracts = seed_contracts(shops, tenants)
	seed_payments(contracts)
	finish_leads(leads, shops)
	seed_refusals(shops, contracts)
	frappe.db.commit()
	print("\nDone. Open /app/airport-shops, /shops and the Demo flight. Clean up with airplane_mode.demo.clear")


# ---------------------------------------------------------------- Part 1


def seed_flights():
	airline = frappe.get_doc({"doctype": "Airline", "customer_care_number": "100", "headquarters": "Cairo"})
	airline.name = f"{MARK} Air"
	airline.insert()
	airplane = frappe.get_doc({"doctype": "Airplane", "model": "A320 Demo", "airline": airline.name, "capacity": 20}).insert()
	for name, code in ((NORTH, "DMN"), (SOUTH, "DMS")):
		doc = frappe.get_doc({"doctype": "Airport", "code": code, "city": "Demo City", "country": "Demoland"})
		doc.name = name
		doc.insert()

	crew = {
		role: frappe.get_doc({"doctype": "Crew Member", "full_name": f"{MARK} {who}", "crew_role": role,
			"email": f"{who.lower()}@example.com"}).insert().name
		for who, role in (("Ahmed", "Pilot"), ("Karim", "Co-Pilot"), ("Mona", "Cabin Crew"))
	}
	flight = frappe.get_doc({
		"doctype": "Airplane Flight", "airplane": airplane.name, "date_of_departure": add_days(today(), 14),
		"time_of_departure": "09:30:00", "duration": 7200, "source_airport": NORTH, "destination_airport": SOUTH,
		"gate_number": "A1",
		"crew": [{"crew_member": crew["Pilot"]}, {"crew_member": crew["Co-Pilot"]},
			{"crew_member": crew["Cabin Crew"], "crew_role": "Pilot"}],  # tampered role on purpose
	}).insert()
	log(1, f"flight {flight.name} with 3 crew members")
	log(3, f"Mona's tampered role saved as '{flight.crew[2].crew_role}'")
	refused(2, "same crew member twice", lambda: _dup_crew(flight.name, crew["Pilot"]))

	tickets = {}
	for label, boarded in (("draft", False), ("submitted", True), ("cancelled", True)):
		pax = frappe.get_doc({"doctype": "Flight Passenger", "first_name": f"{MARK} {label.title()}",
			"last_name": "Passenger", "date_of_birth": "1990-01-01"}).insert()
		t = frappe.get_doc({"doctype": "Airplane Ticket", "passenger": pax.name, "flight": flight.name,
			"flight_price": 150, "status": "Boarded" if boarded else "Booked"}).insert()
		if boarded:
			t.submit()
		tickets[label] = t
	tickets["cancelled"].cancel()
	log(4, f"3 tickets got gate {tickets['draft'].gate_number}")

	flight.reload()
	flight.submit()
	flight.reload()
	flight.gate_number = "B7"
	flight.save()  # queues the background job after commit (case 5)
	log(5, "gate changed A1 -> B7 on the submitted flight (background job queued)")
	changed = update_ticket_gate_numbers(flight.name)  # also apply now, so the data is ready without the worker
	log(8, f"tickets updated now: {changed}; draft + submitted show B7")
	log(9, f"cancelled ticket keeps {frappe.db.get_value('Airplane Ticket', tickets['cancelled'].name, 'gate_number')}")
	log(10, f"running the job again changes {update_ticket_gate_numbers(flight.name)} tickets")


def _dup_crew(flight_name, crew_member):
	doc = frappe.get_doc("Airplane Flight", flight_name)
	doc.append("crew", {"crew_member": crew_member})
	doc.save()


# ---------------------------------------------------------------- Part 2: shops and tenants


def seed_shops():
	frappe.get_doc({"doctype": "Shop Type", "shop_type_name": f"{MARK} Kiosk", "enabled": 0}).insert()
	log(105, "shop type 'Demo Kiosk' is disabled, so it is hidden in the Shop Type dropdown")

	specs = {
		"coffee": ("A1", "Demo Coffee Corner", "Stall", 40, 1000, NORTH, 1),
		"books": ("A2", "Demo Book Nook", "Normal", 60, 0, NORTH, 1),  # rent 0 -> default from settings
		"dutyfree": ("A3", "Demo Duty Free", "Walk-through", 300, 2000, NORTH, 1),
		"pharmacy": ("A4", "Demo Pharmacy", "Normal", 80, 1000, NORTH, 1),
		"electronics": ("A5", "Demo Electronics", "Normal", 120, 1500, NORTH, 1),
		"fashion": ("A6", "Demo Fashion", "Walk-through", 150, 1800, NORTH, 1),
		"bank": ("A7", "Demo Bank Branch", "Normal", 70, 1200, NORTH, 1),
		"hidden": ("B1", "Demo Hidden Unit", "Stall", 20, 500, NORTH, 0),
		"south": ("S1", "Demo South Cafe", "Stall", 30, 900, SOUTH, 1),
	}
	shops = {}
	for key, (number, name, stype, area, rent, airport, published) in specs.items():
		shops[key] = frappe.get_doc({
			"doctype": "Airport Shop", "shop_number": number, "shop_name": name, "shop_type": stype,
			"area": area, "rent_amount": rent, "airport": airport, "published": published,
			"description": f"<p>{name} – demo shop for the Assignment 4 walkthrough.</p>",
			"status": "Occupied" if key == "coffee" else None,  # case 17: ignored on insert
		}).insert()
	log(13, f"shop names use the airport code: {shops['coffee'].name}, {shops['south'].name}")
	log(16, f"{shops['books'].name} saved with rent 0 -> default {shops['books'].rent_amount}")
	log(17, f"{shops['coffee'].name} sent status Occupied on insert -> stored as {shops['coffee'].status}")
	log(83, f"{shops['hidden'].name} is unpublished (not on /shops)")

	moving = frappe.get_doc({"doctype": "Airport Shop", "shop_number": "M1", "shop_name": "Demo Moving Kiosk",
		"shop_type": "Stall", "area": 15, "rent_amount": 400, "airport": SOUTH}).insert()
	moving.airport = NORTH
	moving.save()
	log(22, f"{moving.name} moved {SOUTH} -> {NORTH} (keeps its name); both airports' counts updated")

	tenants = {
		key: frappe.get_doc({"doctype": "Tenant", "tenant_name": f"{MARK} {who}", "company": company,
			"email": f"{key}.tenant@example.com", "phone": "+20 100 000 0000"}).insert()
		for key, who, company in (
			("bean", "Bean Brothers", "Bean Bros LLC"), ("lux", "Lux Retail", "Lux Group"),
			("volt", "Volt Gadgets", "Volt Ltd"), ("vogue", "Vogue Wear", "Vogue Co"),
			("bank_a", "First Bank", "First Bank PLC"), ("bank_b", "Second Bank", "Second Bank PLC"),
			("care", "CarePlus", "CarePlus Pharma"), ("page", "Page Turners", "Page Turners"),
		)
	}
	return shops, tenants


# ---------------------------------------------------------------- leads (before contracts, so they convert)


def seed_leads(shops):
	def lead(key, who, shop, email, status="New", msg=""):
		return frappe.get_doc({"doctype": "Shop Lead", "lead_name": f"{MARK} {who}", "email": email,
			"phone": "+20 111 111 1111", "shop": shops[shop].name, "status": status,
			"message": msg or f"I'd like to rent {shops[shop].shop_name}."}).insert()

	leads = {
		"new": lead("new", "Sara Visitor", "fashion", "sara@example.com"),
		"contacted": lead("contacted", "Omar Prospect", "south", "omar@example.com"),
		"by_email": lead("by_email", "Bean Brothers", "coffee", "bean.tenant@example.com"),
		"lost": lead("lost", "Bean Brothers (old)", "coffee", "bean.tenant@example.com", status="Lost"),
		"amend": lead("amend", "Page Turners", "books", "page.tenant@example.com"),
	}
	refused(90, "lead for an unpublished shop", lambda: lead("x", "Nobody", "hidden", "x@example.com"))
	tenant = create_tenant(leads["contacted"].name)
	log(91, f"Create Tenant on {leads['contacted'].name} -> {tenant}, lead Contacted")
	log(93, f"clicking again returns the same tenant: {create_tenant(leads['contacted'].name)}")
	log(94, f"Create Tenant on Lost lead {leads['lost'].name}: status stays "
		f"{_status_after_create_tenant(leads['lost'].name)}")
	return leads


def _status_after_create_tenant(lead):
	create_tenant(lead)
	return frappe.db.get_value("Shop Lead", lead, "status")


# ---------------------------------------------------------------- contracts


def contract(shop, tenant, start, end, rent=None, submit=True):
	doc = frappe.get_doc({"doctype": "Shop Contract", "shop": shop.name, "tenant": tenant.name,
		"start_date": start, "end_date": end, "rent_amount": rent or shop.rent_amount}).insert()
	if submit:
		doc.submit()
	return doc


def seed_contracts(shops, tenants):
	t = today()
	c = {}
	c["coffee"] = contract(shops["coffee"], tenants["bean"], add_days(t, -40), add_days(add_months(add_days(t, -40), 12), -1))
	log(40, f"{c['coffee'].name}: active, {shops['coffee'].name} Occupied, {len(c['coffee'].rent_schedule)} periods")

	start = add_days(t, -20)
	c["dutyfree"] = contract(shops["dutyfree"], tenants["lux"], start, add_days(add_months(start, 2), 9))
	last = c["dutyfree"].rent_schedule[-1]
	log(26, f"{c['dutyfree'].name}: last period {last.period_start}..{last.period_end} prorated to {last.amount}")

	c["electronics"] = contract(shops["electronics"], tenants["volt"], add_days(t, 10), add_days(t, 190))
	log(41, f"{c['electronics'].name}: starts in 10 days -> {shops['electronics'].name} stays Available until then")

	c["fashion"] = contract(shops["fashion"], tenants["vogue"], add_days(t, -200), add_days(t, -20))
	log(42, f"{c['fashion'].name}: ended 20 days ago -> {shops['fashion'].name} Available")

	c["bank_a"] = contract(shops["bank"], tenants["bank_a"], add_days(t, -60), add_days(t, 20))
	c["bank_b"] = contract(shops["bank"], tenants["bank_b"], add_days(t, 21), add_days(t, 200))
	log(43, f"back-to-back on {shops['bank'].name}: {c['bank_a'].name} then {c['bank_b'].name} (no gap on the switch day)")

	c["pharmacy"] = contract(shops["pharmacy"], tenants["care"], "2027-01-31", "2027-04-29")
	log(27, "31 Jan start: periods " + ", ".join(str(r.period_start) for r in c["pharmacy"].rent_schedule))

	original = contract(shops["books"], tenants["page"], add_days(t, -5), add_days(t, 85))
	log(97, f"{original.name} converted the Page Turners lead")
	original.reload()
	original.cancel()
	log(101, f"{original.name} cancelled -> lead back to Contacted, shop Available")
	amended = frappe.copy_doc(original)
	amended.docstatus = 0
	amended.amended_from = original.name
	amended.insert()
	amended.submit()
	c["books"] = amended
	log(46, f"amended {amended.name}: fresh schedule of {len(amended.rent_schedule)} Unpaid periods; lead Converted again")
	return c


# ---------------------------------------------------------------- payments


def payment(contract_doc, period, amount, mode="Cash"):
	doc = frappe.get_doc({"doctype": "Rent Payment", "shop_contract": contract_doc.name, "period_start": period,
		"amount": amount, "mode_of_payment": mode, "reference_no": "DEMO"}).insert()
	doc.submit()
	return doc


def seed_payments(c):
	rows = c["coffee"].rent_schedule
	first = payment(c["coffee"], rows[0].period_start, 400)
	payment(c["coffee"], rows[0].period_start, 600, "Bank Transfer")
	first.reload()
	log(50, f"period {rows[0].period_start}: 400 + 600 -> Paid")
	log(51, f"receipt {first.name} keeps 'outstanding after payment' = {first.period_outstanding_after_payment}")

	for amount in (333.33, 333.33, 333.34):
		payment(c["coffee"], rows[1].period_start, amount, "Card")
	log(56, f"period {rows[1].period_start}: 333.33 + 333.33 + 333.34 -> Paid exactly")

	keep = payment(c["coffee"], rows[2].period_start, 400)
	undo = payment(c["coffee"], rows[2].period_start, 250)
	undo.cancel()
	log(54, f"period {rows[2].period_start}: paid 400 + 250, then {undo.name} cancelled -> Partly Paid with 400")

	rounded = payment(c["dutyfree"], c["dutyfree"].rent_schedule[0].period_start, 500.004)
	log(57, f"{rounded.name}: 500.004 stored as {rounded.amount}")
	c["coffee"].reload()
	log(34, f"{c['coffee'].name} totals: paid {c['coffee'].total_paid}, outstanding {c['coffee'].total_outstanding}")
	return keep


def finish_leads(leads, shops):
	states = frappe.get_all("Shop Lead", filters={"name": ["in", [l.name for l in leads.values()]]},
		fields=["name", "lead_name", "status", "tenant", "shop_contract"])
	for s in states:
		log("89-103", f"{s.name} {s.lead_name}: {s.status}, tenant={s.tenant or '-'}, contract={s.shop_contract or '-'}")


# ---------------------------------------------------------------- cases that must be refused


def seed_refusals(shops, c):
	t = today()
	refused(14, "duplicate shop number at the same airport", lambda: frappe.get_doc({"doctype": "Airport Shop",
		"shop_number": "A1", "shop_name": "Dup", "airport": NORTH}).insert())
	refused(18, "editing status by hand", lambda: _edit(shops["coffee"].name, status="Available"))
	refused(23, "moving a shop that has a contract", lambda: _edit(shops["electronics"].name, airport=SOUTH))
	someone = frappe.get_doc("Tenant", c["coffee"].tenant)
	refused(35, "end date before start date", lambda: contract(shops["south"], someone, "2027-02-10", "2027-02-01", submit=False))
	refused(37, "overlapping contract", lambda: contract(shops["coffee"],
		frappe.get_doc("Tenant", c["dutyfree"].tenant), t, add_days(t, 30), submit=False))
	refused(45, "cancelling a contract that has payments", lambda: frappe.get_doc("Shop Contract", c["coffee"].name).cancel())
	first = c["coffee"].rent_schedule[0].period_start
	refused(52, "overpaying a paid period", lambda: payment(c["coffee"], first, 1))
	refused(58, "zero payment", lambda: payment(c["coffee"], c["coffee"].rent_schedule[3].period_start, 0))
	refused(59, "payment for a period that doesn't exist", lambda: payment(c["coffee"], add_days(first, 3), 100))


def _edit(shop, **values):
	doc = frappe.get_doc("Airport Shop", shop)
	doc.update(values)
	doc.save()


# ---------------------------------------------------------------- clean up


def clear():
	"""Remove everything seed() made (cancels submitted docs first)."""
	frappe.flags.mute_emails = True
	demo_contracts = frappe.get_all("Shop Contract", filters={"shop": ["like", "DM%"]}, pluck="name")
	for name in frappe.get_all("Rent Payment", filters={"shop_contract": ["in", demo_contracts or [""]],
			"docstatus": 1}, pluck="name"):
		frappe.get_doc("Rent Payment", name).cancel()
	for name in frappe.get_all("Rent Payment", filters={"shop_contract": ["in", demo_contracts or [""]]}, pluck="name"):
		frappe.delete_doc("Rent Payment", name, force=1)
	for name in frappe.get_all("Shop Contract", filters={"name": ["in", demo_contracts or [""]], "docstatus": 1}, pluck="name"):
		frappe.get_doc("Shop Contract", name).cancel()
	for name in frappe.get_all("Shop Lead", filters={"lead_name": ["like", f"{MARK} %"]}, pluck="name"):
		frappe.delete_doc("Shop Lead", name, force=1)
	for name in sorted(demo_contracts, reverse=True):  # amendments before originals
		frappe.delete_doc("Shop Contract", name, force=1)
	for name in frappe.get_all("Airport Shop", filters={"airport": ["in", [NORTH, SOUTH]]}, pluck="name"):
		frappe.delete_doc("Airport Shop", name, force=1)
	for name in frappe.get_all("Tenant", filters={"tenant_name": ["like", f"{MARK} %"]}, pluck="name"):
		frappe.delete_doc("Tenant", name, force=1)
	if frappe.db.exists("Shop Type", f"{MARK} Kiosk"):
		frappe.delete_doc("Shop Type", f"{MARK} Kiosk", force=1)

	flights = frappe.get_all("Airplane Flight", filters={"source_airport": NORTH}, pluck="name")
	tickets = frappe.get_all("Airplane Ticket", filters={"flight": ["in", flights or [""]]}, fields=["name", "docstatus", "passenger"])
	for t in tickets:
		if t.docstatus == 1:
			frappe.get_doc("Airplane Ticket", t.name).cancel()
		frappe.delete_doc("Airplane Ticket", t.name, force=1)
		frappe.delete_doc("Flight Passenger", t.passenger, force=1)
	for f in flights:
		if frappe.db.get_value("Airplane Flight", f, "docstatus") == 1:
			frappe.get_doc("Airplane Flight", f).cancel()
		frappe.delete_doc("Airplane Flight", f, force=1)
	for name in frappe.get_all("Crew Member", filters={"full_name": ["like", f"{MARK} %"]}, pluck="name"):
		frappe.delete_doc("Crew Member", name, force=1)
	for name in frappe.get_all("Airplane", filters={"airline": f"{MARK} Air"}, pluck="name"):
		frappe.delete_doc("Airplane", name, force=1)
	for doctype, name in (("Airline", f"{MARK} Air"), ("Airport", NORTH), ("Airport", SOUTH)):
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, force=1)
	frappe.db.commit()
	print("Demo data removed.")

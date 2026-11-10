from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.doctype.shop_contract.shop_contract import ShopContract
from airplane_mode.airport_shops.tests.factories import make_airport, make_contract, make_shop, make_tenant
from airplane_mode.airport_shops.utils import sync_shop_status


def shop_state(shop):
	return frappe.db.get_value(
		"Airport Shop", shop.name, ["status", "current_tenant", "current_contract", "contract_expiry"], as_dict=True
	)


def amend(doc):
	"""What the Desk Amend button does for a cancelled doc."""
	amended = frappe.copy_doc(doc)
	# copy_doc clears docstatus only when not frappe.flags.in_test, so reset it like the Desk does.
	amended.docstatus = 0
	amended.amended_from = doc.name
	return amended


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

	def test_before_submit_rechecks_overlap_with_locking_read(self):
		# validate() already rejects the clash, so call before_submit directly to prove it
		# re-checks on its own. True two-connection concurrency is checked manually.
		shop = make_shop()
		first = make_contract(shop, start="2027-01-01", end="2027-03-31", submit=False)
		second = make_contract(shop, start="2027-02-01", end="2027-04-30", submit=False)
		first.submit()
		second.docstatus = 1
		with self.assertRaises(frappe.ValidationError):
			second.before_submit()

		third = make_contract(shop, start="2027-05-01", end="2027-06-30", submit=False)
		with patch.object(
			ShopContract, "validate_no_overlap", autospec=True, side_effect=ShopContract.validate_no_overlap
		) as check:
			third.submit()
		check.assert_any_call(third, for_update=True)

	def test_zero_rent_rejected(self):
		# rent_amount is fetch_if_empty from the shop, so a 0 would be refilled from the shop's
		# rent. Zero the shop's rent too (before_insert would replace a 0 with the default).
		shop = make_shop()
		frappe.db.set_value("Airport Shop", shop.name, "rent_amount", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "greater than zero"):
			make_contract(shop, start="2027-01-01", end="2027-03-31", rent=0)

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
		airport = make_airport()
		shop = make_shop(airport)
		a = make_contract(shop, start="2026-09-01", end="2026-11-30")
		b_tenant = make_tenant()
		b = make_contract(shop, b_tenant, start="2026-12-01", end="2027-05-31")
		sync_shop_status(shop.name, on_date="2026-11-30")
		self.assertEqual(shop_state(shop).current_contract, a.name)
		self.assertEqual(frappe.db.get_value("Airport", airport.name, "occupied_shops"), 1)
		sync_shop_status(shop.name, on_date="2026-12-01")
		state = shop_state(shop)
		self.assertEqual(frappe.db.get_value("Airport", airport.name, "occupied_shops"), 1)
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

		amended = amend(contract)
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
		amended = amend(original)
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

	def test_changing_current_contract_through_save_is_rejected(self):
		other = make_contract(make_shop(), start="2027-01-01", end="2027-03-31")
		shop = make_shop()
		shop.current_contract = other.name
		with self.assertRaisesRegex(frappe.ValidationError, "set automatically"):
			shop.save()

	def test_shop_reloaded_after_sync_writes(self):
		shop = make_shop()
		make_contract(shop, start=add_days(today(), -1), end=add_days(today(), 30))
		# Simulate a stale stored status (e.g. the daily job hasn't run yet).
		frappe.db.set_value("Airport Shop", shop.name, "status", "Available")
		shop.reload()
		shop.shop_name = "Renamed"
		shop.save()  # on_update syncs to Occupied and reloads
		self.assertEqual(shop.status, "Occupied")
		shop.shop_name = "Renamed again"
		shop.save()  # in-memory doc isn't stale, so a second save works

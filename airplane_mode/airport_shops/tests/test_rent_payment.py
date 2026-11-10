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

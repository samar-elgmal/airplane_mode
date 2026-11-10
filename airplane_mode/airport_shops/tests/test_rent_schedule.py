from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

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
		self.assertEqual(last.amount, 35.71)

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

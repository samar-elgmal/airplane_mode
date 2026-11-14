# Copyright (c) 2026, samar and Contributors
# See license.txt

import os
import shutil

import frappe
from frappe.model.naming import NamingSeries
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.doctype.airport_announcements import airport_announcements as module

DOCTYPE = "Airport Announcements"


class TestAirportAnnouncements(FrappeTestCase):
	def setUp(self):
		# Work on a copy of the site's file and put the original back after each test:
		# the JSON file is not part of the database transaction, so it is not rolled back.
		self.path = module.get_data_path()
		self.backup = f"{self.path}.test-backup"
		module.read_data()  # make sure the file exists (created from the seed if needed)
		shutil.copyfile(self.path, self.backup)

	def tearDown(self):
		os.replace(self.backup, self.path)

	def make(self, **kwargs):
		return frappe.get_doc(
			{"doctype": DOCTYPE, "title": "Test announcement", "priority": "Low", **kwargs}
		).insert()

	def test_create_writes_to_json_file(self):
		doc = self.make(notes="Created in a test")
		self.assertIn(doc.name, module.read_data())
		self.assertEqual(module.read_data()[doc.name]["notes"], "Created in a test")

	def test_read(self):
		doc = self.make(title="Read me")
		loaded = frappe.get_doc(DOCTYPE, doc.name)
		self.assertEqual(loaded.title, "Read me")
		self.assertEqual(loaded.priority, "Low")

	def test_update(self):
		doc = self.make()
		doc.priority = "High"
		doc.save()
		self.assertEqual(frappe.get_doc(DOCTYPE, doc.name).priority, "High")

	def test_delete(self):
		doc = self.make()
		frappe.delete_doc(DOCTYPE, doc.name)
		self.assertNotIn(doc.name, module.read_data())
		self.assertRaises(frappe.DoesNotExistError, frappe.get_doc, DOCTYPE, doc.name)

	def test_list_and_count_with_filter(self):
		self.make(title="Filter one", priority="High")
		high = module.AirportAnnouncements.get_list({"filters": [[DOCTYPE, "priority", "=", "High"]]})
		self.assertTrue(high)
		self.assertTrue(all(row.priority == "High" for row in high))
		self.assertEqual(
			module.AirportAnnouncements.get_count({"filters": [[DOCTYPE, "priority", "=", "High"]]}), len(high)
		)

	def test_seed_creates_file_when_missing(self):
		os.remove(self.path)
		data = module.read_data()
		self.assertIn("ANN-0001", data)
		self.assertTrue(os.path.exists(self.path))

	def test_new_site_does_not_reuse_seed_names(self):
		# Simulate a new site: counter at 0 and no data file yet (both rolled back / restored).
		series = NamingSeries("ANN-.####")
		series.update_counter(0)
		os.remove(self.path)
		doc = self.make()
		self.assertNotIn(doc.name, ("ANN-0001", "ANN-0002", "ANN-0003"))
		self.assertEqual(doc.name, "ANN-0004")

	def test_counter_raised_when_behind_file(self):
		# Counter behind the file (e.g. a record was added to the file another way).
		series = NamingSeries("ANN-.####")
		highest = max(int(name[4:]) for name in module.read_data() if name.startswith("ANN-"))
		series.update_counter(0)
		doc = self.make()
		self.assertEqual(doc.name, f"ANN-{highest + 1:04d}")

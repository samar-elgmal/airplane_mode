# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

"""Virtual DocType: Airport Announcements are stored in a JSON file, not in a database table.

The file lives in the site's private folder (sites/<site>/private/files/airport_announcements.json),
so every site has its own data and the data never ends up in git. The first time a site reads it,
the file is created from announcements_seed.json, which ships with the app as sample data.

File format: {"<name>": {"name": "<name>", "title": ..., "airport": ..., ...}, ...}
"""

import json
import os
import shutil

import frappe
from frappe.model.document import Document
from frappe.model.naming import NamingSeries
from frappe.utils import cint

DATA_FILE = "airport_announcements.json"
SEED_FILE = os.path.join(os.path.dirname(__file__), "announcements_seed.json")


def get_data_path():
	return frappe.get_site_path("private", "files", DATA_FILE)


def read_data():
	path = get_data_path()
	seeded = False
	if not os.path.exists(path):
		os.makedirs(os.path.dirname(path), exist_ok=True)
		shutil.copyfile(SEED_FILE, path)
		seeded = True
	with open(path) as f:
		data = json.load(f)
	if seeded:
		sync_series_counter(data)
	return data


def sync_series_counter(data):
	"""Raise the naming series counter (ANN-) to the highest number already used in the file.

	The counter lives in the database (tabSeries) and knows nothing about the JSON file, so on a new
	site it starts at 0 and the first new record would be ANN-0001, which the seed data already uses.
	The counter is only ever raised, never lowered.
	"""
	series = NamingSeries(frappe.get_meta("Airport Announcements").autoname)
	prefix = series.get_prefix()
	highest = max(
		(cint(name.removeprefix(prefix)) for name in data if name.startswith(prefix)),
		default=0,
	)
	if highest > series.get_current_value():
		series.update_counter(highest)


def write_data(data):
	# Write to a temp file first, then swap it in, so a crash never leaves a half-written file.
	path = get_data_path()
	tmp_path = f"{path}.tmp"
	with open(tmp_path, "w") as f:
		json.dump(data, f, indent=1, default=str)
	os.replace(tmp_path, path)


class AirportAnnouncements(Document):
	def before_naming(self):
		# Also check right before a new name is taken. Opening the List View is a GET request, and
		# Frappe does not commit GET requests, so a counter update made while seeding there is
		# rolled back. Saving is a POST, so this update is committed together with the new record.
		sync_series_counter(read_data())

	def db_insert(self, *args, **kwargs):
		data = read_data()
		if self.name in data:
			frappe.throw(frappe._("Announcement {0} already exists.").format(self.name), frappe.DuplicateEntryError)
		data[self.name] = self.get_valid_dict(convert_dates_to_str=True)
		write_data(data)

	def load_from_db(self):
		doc = read_data().get(self.name)
		if not doc:
			frappe.throw(
				frappe._("Airport Announcement {0} not found.").format(self.name), frappe.DoesNotExistError
			)
		self.init_from_dict(doc)

	def db_update(self, *args, **kwargs):
		data = read_data()
		data[self.name] = self.get_valid_dict(convert_dates_to_str=True)
		write_data(data)

	def delete(self, *args, **kwargs):
		data = read_data()
		data.pop(self.name, None)
		write_data(data)

	@staticmethod
	def get_list(args=None):
		args = frappe._dict(args or {})
		rows = apply_filters(read_data().values(), args.get("filters"))

		# order_by arrives like "`tabAirport Announcements`.`modified` desc"
		field, _, direction = (args.get("order_by") or "modified desc").partition(" ")
		field = field.split(".")[-1].strip("`")
		rows.sort(key=lambda row: str(row.get(field) or ""), reverse=direction.strip().lower() != "asc")

		start = cint(args.get("start"))
		page_length = cint(args.get("page_length")) or len(rows)
		return [frappe._dict(row) for row in rows[start : start + page_length]]

	@staticmethod
	def get_count(args=None):
		args = frappe._dict(args or {})
		return len(apply_filters(read_data().values(), args.get("filters")))

	@staticmethod
	def get_stats(args=None):
		return {}


def apply_filters(rows, filters):
	"""Support the simple filters the List View sends: equals, not equals and like."""
	rows = list(rows)
	if not filters:
		return rows
	if isinstance(filters, str):
		filters = json.loads(filters)
	if isinstance(filters, dict):
		filters = [[None, field, "=", value] for field, value in filters.items()]

	for f in filters:
		field, operator, value = f[-3], f[-2].lower(), f[-1]
		if operator == "=":
			rows = [r for r in rows if str(r.get(field) or "") == str(value)]
		elif operator == "!=":
			rows = [r for r in rows if str(r.get(field) or "") != str(value)]
		elif operator == "like":
			needle = str(value).strip("%").lower()
			rows = [r for r in rows if needle in str(r.get(field) or "").lower()]
	return rows

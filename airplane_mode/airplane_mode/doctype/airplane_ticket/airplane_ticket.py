# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import random

class AirplaneTicket(Document):
	def validate(self):
		self.remove_duplicate_add_ons()
		self.validate_capacity()

		total = self.flight_price or 0
		for item in self.add_ons:
			total += item.amount or 0

		self.total_amount = total

	def remove_duplicate_add_ons(self):
		seen = set()
		unique_add_ons = []

		for item in self.add_ons:
			if item.item in seen:
				continue
			seen.add(item.item)
			unique_add_ons.append(item)

		if len(unique_add_ons) < len(self.add_ons):
			frappe.msgprint("Duplicate add-ons were removed.")

		self.set("add_ons", unique_add_ons)
		for i, item in enumerate(self.add_ons, start=1):
			item.idx = i

	def before_submit(self):
		if self.status != "Boarded":
			frappe.throw("Ticket can only be submitted when status is Boarded")

	def before_insert(self):
		self.seat = generate_seat()

		
	def validate_capacity(self):
		airplane = frappe.db.get_value("Airplane Flight", self.flight, "airplane")

		capacity = frappe.db.get_value("Airplane", airplane, "capacity") or 0

		booked_tickets = frappe.db.count(
			"Airplane Ticket",
			{
				"flight": self.flight,
				"docstatus": ["!=", 2],
				"name": ["!=", self.name]
			}
		)

		if booked_tickets >= capacity:
			frappe.throw(
				"No available seats on this flight!"
			)


def generate_seat():
	number = random.randint(1, 99)
	letter = random.choice("ABCDE")
	return f"{number}{letter}"

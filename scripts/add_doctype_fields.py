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

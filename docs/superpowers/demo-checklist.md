# Day 4 demo checklist

Follow the assignment page top to bottom. Site: http://localhost:8001

## Part 1
- [ ] **Crew:** open a flight and add a Pilot and Cabin Crew in the Crew table. Adding the same person twice is refused.
- [ ] **Gate on tickets:** a ticket shows the Gate Number of its flight.
- [ ] **Gate background job:**
  - On a submitted flight, change the gate and click **Update**.
  - Open `/app/rq-job`; the `update_ticket_gate_numbers` job is there.
  - Open a ticket; it shows the new gate.
  - Explain: the job runs after commit, reads the latest gate from the DB, and is safe to run twice (no dedupe, so a fast second change is never lost).

## Part 2
- [ ] **Module Def:** "Airport Shops" in the sidebar, with the workspace showing the number cards and shortcuts.
- [ ] **Airport Shop form:** number, name, airport, type, area, rent, image, description. Status and tenant are read-only and filled automatically.
- [ ] **Tenant form:** name, email, phone, company.
- [ ] **Shop Contract:**
  - Choose shop and tenant, set the dates and rent, then submit.
  - The Rent Schedule is generated. Show a contract ending mid-month so the last period is prorated.
  - An overlapping contract on the same shop is refused.
- [ ] **Shop becomes Occupied:** the Airport form shows Total / Available / Occupied counts.
- [ ] **Rent Payment:**
  - From the contract, click **Record Payment**; the earliest unpaid period is pre-filled.
  - Pay 400 → Partly Paid. Pay 600 → Paid. A 3rd payment is refused (overpay).
  - Print the receipt for the first payment. It shows "Outstanding After Payment" = 600.
- [ ] **Shop counts:** run the **Airport Shop Occupancy** report (chart and table) and point to the number cards.
- [ ] **Airport Shop Settings:**
  - Set the default rent; a new shop with no rent picks it up.
  - Enable reminders, then **Send Reminders Now**. Show `/app/email-queue`.
- [ ] **Scheduler:** `/app/scheduled-job-type`, filtered on `airport_shops`, lists two daily jobs (status sync and rent reminders).
- [ ] **How the payment schedule works** (explain):
  - Periods are counted from the contract start date, e.g. 15th to 14th.
  - A short last period is prorated by days.
  - Partial payments are allowed and overpaying is blocked.
  - Row locks stop two payments from overpaying at the same time.
- [ ] **Gate number scenario:** already shown in Part 1.

## Web portal
- [ ] `/shops`: the list uses Picnic styling and does not extend `web.html`. Filter by airport.
- [ ] Click a shop to open `/shops/<name>` with its details and **Interested? Apply to rent**.
- [ ] The web form opens with the Shop pre-filled. Submit it, then show the new **Shop Lead** in the desk.

## Part 3
- [ ] **Shop Type list:** Stall, Walk-through and Normal are shipped as fixtures (`fixtures/shop_type.json`).
- [ ] **Enabled filter:** untick **Enabled?** on one type; it disappears from the Shop Type dropdown on the shop form.
- [ ] **Bruno:**
  - Open `bruno/airplane_mode` and select the environment **local**.
  - Paste the API key and secret (User → Settings → API Access → Generate Keys).
  - **List Shops (all fields)** → 200.
  - **Create Shop** → 200. Status comes back "Available" even though the body sent "Occupied".
  - Show the `Authorization: token key:secret` header, then remove it → 403.
  - Optional: keys of a Travel Agent user → no tenant fields (field-level permissions).

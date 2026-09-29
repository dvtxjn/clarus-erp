# Customs Clearance ERP — System Specification (Living Document)

> Status: **v0.4 — ready to build.** All core design decisions are confirmed. Remaining open items (§6) have safe, stated defaults and should not block starting.

---

## 0. How to Use This Document (read this first if you're the build agent)

1. **This spec is the source of truth for requirements and decisions — but not for exact implementation detail on Module 3.** Sections 5.1, 5.3, 5.4, and 5.6 summarize the logic in the client's existing reference tool (`be_expense_sheet.py`, uploaded alongside this spec) faithfully, but a summary can drop precision that matters (exact regex patterns, exact Excel cell references, edge-case handling). **Before implementing any extraction, calculation, or Excel-writing logic, read `be_expense_sheet.py` directly** — it is well-commented and every function referenced in §5.1/§5.3/§5.6 exists there verbatim. Treat this spec as the "what and why," and the script as the "exact how" for anything it already solves. **One explicit exception: do NOT port the reference tool's fixed-cell charge layout (§5.3/§5.6) — that part of the old implementation is a known limitation being fixed, not a pattern to copy.**
2. **Also read `Clarus_Logistics_Proforma_Invoice_flexible.xlsm`** (the invoice template, uploaded) directly to see the exact cell layout, formulas, and formatting the generated proforma/bill must reproduce — §5.6 describes it but doesn't substitute for opening it.
3. **Build order implied by this spec:** Module 1 (Shipment Tracker) is the foundation everything else hooks into — build it first. Module 2 (Document Manager) depends on Module 1's shipment records existing. Module 3 (Proforma & Billing) can be built in parallel with Module 2 once Module 1's data model is stable, since its extraction logic is independent, but its "Billed" status needs to write back to Module 1.
4. **Explicitly out of v1 scope:** ICEGATE/CFS portal scraping (§4), final-bill document generation if it ends up staying in LiveImpex (§5.5). Do not build these unless asked.
5. **Aesthetic requirement is not optional** (§1) — this is a named client requirement, not a nice-to-have, and applies to every screen, not just the one Tkinter screen called out as the specific example.

---

## 1. System Overview

**Design principle (explicit client requirement):** the app must be aesthetic — modern, clean UI throughout. This is called out specifically because the reference tool (§5.6) that this module replaces has a functional but dated/dense Tkinter interface (particularly its "Batch Fee Input" grid — 18 cramped columns, tiny fonts, no visual hierarchy). The web app should **not port that UI as-is**; it should be redesigned as a proper modern interface while keeping 100% of its underlying logic.

A web application for an end-to-end customs clearance shipment lifecycle, consisting of three connected modules:

1. **Shipment Tracker** — core system of record for every shipment, milestone tracking, ETAs, customizable grid views, role/port-based visibility.
2. **Document Manager** — PDF upload, tagging/classification, auto-renaming per syntax, auto-filing, and auto-updates to the Shipment Tracker on upload.
3. **Proforma & Billing Engine** — multi-source PDF data extraction (via `pdfplumber`), proforma generation with versioning, charge master selection, and final billing with archival.

Supporting layer:
- **Automation/Scraping Layer** (Playwright) — **Phase 2 / deprioritized.** For v1, staff will manually feed shipment data (they will be trained on the system). One exception that IS in scope for v1: automated **daily duty challan extraction** (see §5.1a) since this is a defined, high-value, low-ambiguity pull.

---

## 2. Module 1: Shipment Tracker

### 2.1 Shipment — Core Identifiers
- **Primary tracking keys:** MBL number + Job number, and HBL number where applicable (i.e., if HBL exists, shipment is tracked via MBL+HBL+Job together)
- **Secondary tracking keys:** Bill of Entry (BE) number + BE date

### 2.2 Shipment Fields (initial list — 26 fields, more may be added)
| Field | Notes |
|---|---|
| Job | |
| MBL | |
| BE Description | |
| ETA | |
| INW | |
| Day | |
| License | |
| Client | |
| Consignee | |
| POD | Port of Discharge |
| Container Status | |
| CFS | |
| BE No | |
| BE Dt | |
| Container | |
| Gross Wt | |
| Remark | |
| POC | |
| Remarks | **Resolved:** this is the free-text field explaining *why* a shipment is stuck (used with the "Stuck" flag — see §2.3). Whether "Remark" (singular) and "Remarks" (plural) end up as one consolidated field or stay distinct is a minor implementation detail, not a design gap — default to merging into one field unless client says otherwise. |
| Cleared Date | |
| Duty Paid? | Yes/No flag |
| CFS Inv? | Yes/No flag |
| Line Paid? | Yes/No flag |
| OOC? | Yes/No flag |
| DO? | Yes/No flag |
| IGM | |
| Delivery Status | |

**Confirmed:** HBL gets its own column. Data model should technically allow multiple HBLs per MBL (consolidated shipments), but this is a rare/edge case ("one in a million") for this client — not a priority for v1 UI/UX, just shouldn't be architecturally blocked.

### 2.3 Milestones / Status Pipeline (v1 — confirmed)

Linear base pipeline (kept intentionally simple for v1; not heavily branched):

1. **To be Filed**
2. **IGM Filed**
3. **BE Filed**
4. **BE Assessed**
5. **Duty Paid**
6. **Under OOC**
7. **OOC Done**
8. **Cleared**

**Key distinction — OOC Done vs Cleared:**
- **OOC Done** = triggered automatically the moment an OOC Bill of Entry PDF is uploaded & tagged. This is a *document-driven* status, not a manual one.
- **Cleared** = only set when **Gatepass** is done (i.e. the container has physically exited for delivery at the yard). This is a distinct, later event — a shipment can be "OOC Done" for a while before it's "Cleared."
- These are NOT the same milestone. OOC being uploaded does not mean the shipment is cleared.

**No complex branching for v1.** Instead of modeling every exception/stuck state as a separate pipeline branch:
- Keep a **"Stuck" flag** (boolean or status override) on the shipment
- Pair it with a **free-text Remarks field** explaining *why* it's stuck (this is the existing "Remark"/"Remarks" field — see resolution below)
- This keeps the pipeline linear/simple while still surfacing exceptions in grid views (e.g. filter/sort by "Stuck = Yes")

**[OPEN — future/Phase 2]** — If stuck-reasons start repeating in a pattern, may be worth converting free-text remarks into a structured "stuck reason" dropdown later. Not needed for v1.

### 2.4 Users, Roles & Visibility

**Confirmed principles:**
- **Roles:** Admin, Import Manager, Export Manager, Accountant
- **Admin** — full permissions, can change/delete anything
- **Non-admin roles (Import Manager, Export Manager, Accountant)** — can view and add data, but **cannot delete** without admin approval (i.e. delete = request/approval flow, not a direct action)
- **Version history required on all changes, retained for 7 days**
- **Proforma & Billing module access is permission-gated** — not every role sees/edits this module; access assigned per user (Accountant role is the obvious default for this, but should remain independently toggleable rather than hardcoded to the role name)
- Shipment visibility: visible to everyone by default, **restrictable by port** — a user can be scoped to see only shipments for their assigned port(s)

**[OPEN]** — Exact permission matrix per role (e.g. can Import Manager edit Export shipments, does Accountant have view-only access to the tracker fields vs. full edit on billing data) — reasonable defaults can be proposed at build time and confirmed, not a blocker.

### 2.5 Grid Views
- **Per-user customizable views** — not a single shared view; each user can configure their own
- Must support **multiple saved views per user** (e.g. grouped by port, by status, by client) — not just one custom view each, but a set they can switch between
- **[OPEN]** — Specific default view templates to ship with (can be designed once field list is finalized)

---

## 3. Module 2: Document Manager

### 3.1 Document Types (tag taxonomy)
Base set (applies to all/most shipments):
1. CFS Proforma Invoice
2. CFS Tax Invoice
3. Assessed Bill of Entry
4. OOC Bill of Entry
5. Gatepass Bill of Entry
6. BL Copy
7. HBL Copy (if applicable)
8. Packing List
9. Insurance (if applicable)
10. DO Letter
11. Empty Letter
12. HSS & Stamp Duty (if applicable)
13. Certificate of Origin
14. FTA Certificate of Origin (if shipment is under FTA)
15. Form 6 & Form 9 (tyre shipments specifically)

**Extensible taxonomy note:** Document type list must be **customizable based on HS code** of the imported item — i.e. certain HS codes trigger additional required/expected document types beyond the base set above.

**Current state:** Client currently only handles **one HS code (tyre shipments)** in practice — this is why Form 6 & Form 9 are in the base list above. All required documents for this HS code are already known/mapped.

**Required feature (v1):** An **HS-code management interface** where:
- New HS codes can be added to the system
- Each HS code has its own configurable list of required documents
- When a shipment is tagged/created with a given HS code, its specific required-document checklist **auto-populates/pops up** in the Document Manager for that shipment

This makes the taxonomy config-driven rather than hardcoded — starts with just the tyre HS code mapped, but the interface must support adding more over time without a code change.

### 3.2 Auto-Naming on Upload
- **Confirmed naming syntax (two states, based on whether BE has been filed yet):**
  - **Before BE is filed:** `{Document Type} - {BL Number}` (e.g. a Packing List tagged before filing → `PL - {BL No}`)
  - **After BE Number is generated:** `{Document Type} - {BL Number} - {BE Number}`
- **Core intent:** naming must cleanly identify document type + BL number (+ BE number once available), so any document is instantly identifiable and retrievable from the filename alone — combined with in-interface tagging, retrieval should be near-instant ("on your fingertips").
- **[OPEN]** — Confirm exact abbreviation/token used per document type in the filename (e.g. is Packing List always "PL", is OOC Bill of Entry "OOC", etc.) — client has 2 existing Python scripts encoding this that can be shared if a full canonical list is needed, though the pattern above may be sufficient to implement directly.

### 3.3 Auto-Extraction & Tracker Sync on Upload
- On upload, if tagged as a specific doc type, the system extracts relevant fields directly from the PDF (via `pdfplumber`) and updates the Shipment Tracker automatically.
- **Confirmed example:** Uploading & tagging a PDF as "OOC Bill of Entry" → system reads the OOC date from the PDF itself → auto-updates `Cleared Date` (or dedicated OOC date field) and sets `OOC? = Yes` in the tracker.
- **[OPEN]** — This same auto-extract-and-sync behavior likely applies to other doc types too (e.g. Duty Challan → `Duty Paid? = Yes`) — confirm full list of doc type → tracker field mappings.

---

## 4. Automation / Scraping Layer

### 4.1 Sources
- **ICEGATE** — public portal used by clearance agents to pull filing/status data
- **CFS Portals** — for container/cargo tracking data

### 4.2 Trigger Mode
- **Hybrid:** periodic/scheduled auto-pull for certain data, **plus** manual on-demand trigger (button per shipment) for immediate refresh
- **[OPEN]** — Which specific data points are scraped from where (e.g. IGM number from ICEGATE, container status from CFS portal), and what the polling frequency should be

### 4.3 Tooling
- Playwright-based scraping (browser automation against portals that don't offer clean APIs)

---

## 5. Module 3: Proforma & Billing Engine

### 5.1 Data Extraction — CONFIRMED (from reference tool `be_expense_sheet.py`)

Client shared a working Python/Tkinter tool ("BE Expense Sheet", v7.2) that already does this extraction reliably in production. This is a direct reference implementation — the web app's extraction logic should port this, not redesign it.

**PDF classification (auto-routing):** a mixed batch of PDFs (BE + CFS invoices together) is auto-classified per file via a scored-signal approach — e.g. presence of "BILL OF ENTRY" / "1. IMPORTER NAME" pattern scores toward BE, "CONTAINER FREIGHT STATION" / "TOTAL AMOUNT BEFORE TAX" scores toward CFS. Ties default to BE. This lets one upload/selection handle both document types without the user manually separating them first.

**Fields extracted from Bill of Entry (BE) PDF:**
| Field | Extraction method |
|---|---|
| Port Code | Regex on ICEGATE-style port code pattern (`IN[A-Z]{3}\d`) |
| BE Number | Regex anchored near port code, falls back to any 7-digit number in text |
| BE Date | Regex across common date formats, normalized to `DD.MM.YYYY` |
| Importer Name | 3-tier fallback strategy: (1) block of text after "1.IMPORTER NAME" label, (2) same-line match with company suffix (LTD/PVT/LLC etc.), (3) looser block match |
| AD Code | Regex near "AD CODE" label, 7-digit code |
| MAWB / HAWB (MBL/HBL) | Extracted via word-position anchoring on the manifest header row |
| Container Count | Counts unique ISO container number patterns (`[A-Z]{4}\d{7}`), with text-based fallback |
| Gross Weight | Position-anchored to the same manifest header row as MAWB/HAWB (PKG/GW columns), with a text-label fallback ("G.WT") if position anchoring fails |
| Assessable Value, IGST, Total Duty Amount | Extracted from the BCD/duty summary block by locating labeled rows and reading the numeric line(s) beneath them |

**Fields extracted from CFS Proforma/Tax Invoice PDF:**
| Field | Extraction method |
|---|---|
| BE Number | Regex on "BOE No" label |
| BL Number | Regex on "BL No" label |
| CFS Rate (before tax) | Regex on "Total Amount Before Tax" |
| CFS GST | Regex on "Tax Amount: GST" |
| CFS Total (after tax) | Regex on "Total Amount After Tax" |
| Sanity check | Before-tax + GST is checked against After-tax (tolerance <1.0) to catch mis-extraction on an unfamiliar invoice layout |

**CFS-to-BE matching:** once both BE and CFS PDFs are scanned in a batch, CFS invoices are auto-matched to the correct shipment row by BE Number first, falling back to BL Number. This is how a mixed upload of "10 BE PDFs + 6 CFS invoices" self-organizes into the right rows without manual pairing.

**AD Code → Importer Name lookup (Organization Repository):** a separate spreadsheet ("Organization List") acts as a lookup table mapping AD Code → registered organization name. This is used to detect a mismatch between the name printed on the BE and the officially registered name for that AD Code (flags `YES`/`NO`/`N/A` accordingly). This repository is maintained/updatable independent of the main app — **the web app should have an equivalent manageable lookup table**, likely as an admin-editable settings screen rather than a spreadsheet import.

### 5.1a Daily Duty Challan (Interest) — CONFIRMED mechanics
- Source file: a periodically-exported Excel sheet (columns: IEC, Location Code, Doc type, Doc no., Doc date, Challan no., **Due Amount**) listing the *current* duty+GST+interest payable per BE, since interest accrues daily until paid.
- The tool reads this sheet, filters to `Doc type = BE` rows, and builds a `{BE Number: Due Amount}` map.
- In the fee-entry step, if "Interest Applicable" is checked for a row, the **Due Amount from the challan overrides** the BE PDF's own duty total as the final payable figure, and the difference (Due Amount − BE's duty total) is shown separately as the interest-only portion.
- **Confirms §4/§5.1a plan:** this daily challan pull is exactly the Playwright automation kept in v1 scope — same underlying data shape, just needs to go from "manual Excel import" to "scraped every morning automatically."

### 5.2 Proforma Versioning
- **Multiple proformas per shipment** — every time a proforma is revised/resent, a new version is stored against that same shipment (full history retained, not overwritten)
- **Gap vs. reference tool:** the existing tool generates one output file per BE and doesn't track revisions/versions at all — each run just overwrites/produces a new standalone file. **Versioning is a genuinely new requirement** for the web app, not something to port — needs its own data model (e.g. `proforma` records with a `shipment_id`, `version_number`, `created_at`, `status` (draft/sent/superseded), and a snapshot of the line items/fees at that version).

### 5.3 Interactive Update Mechanism
- After auto-extraction, user can interactively edit/adjust proforma line items before finalizing (confirmed)
- **Maps directly to the reference tool's "Batch Fee Input" screen** — a grid with one row per shipment/BE, letting the user set per-shipment charges (rates, checkboxes for which charges apply, interest override, save path) before generating the output.
- **This is the screen flagged for aesthetic redesign** (§1) — same functionality (per-shipment editable charge rows, presets, live validation), rebuilt as a clean modern web UI instead of the current dense 18-column Tkinter table.

**⚠️ Important architectural correction — charge selection must be fully dynamic, not a fixed set of columns/rows.**

The reference tool's charge set (Agency/Other/Exam/Bond/Doc/CFS/Insurance/Royalty/Bill Rate HSS) is **hardcoded** — both as fixed columns in the Batch Fee Input grid *and* as fixed cell references in the `.xlsm` template (e.g. `C21` is always Agency, `C30` is always CFS Rate, etc. — see §5.6). This is exactly why a charge like **Shipping Line Charges isn't wired into the code at all yet** — there's no fixed row/cell allocated for it in the template, so it's currently handled manually outside the tool. This is a real limitation of the reference implementation, not something to preserve.

**New requirement for the web app:** proforma line-item selection must be **interactive and open-ended**, not a fixed set of hardcoded charge slots:
- When building/editing a proforma, the user should be able to **pick which charges apply from the full charge master** (§5.4) — add any charge, remove any charge, not limited to a pre-defined list of 9 (or 17) known types
- Adding a new charge type to the charge master (§5.4's "required interface") should make it **immediately available** to select on any proforma, without needing a template/cell-layout change
- The generated invoice output (proforma/bill document) must therefore be built with a **dynamic line-item table** — as many rows as the user selected charges for that shipment, not a fixed template with blank/zeroed rows for charges that don't apply. This is a meaningful difference from the reference `.xlsm` template's fixed-row layout (§5.6) and needs its own design (e.g. a proper repeating line-items table in the generated document, subtotal/GST/total calculated dynamically off however many rows exist, rather than off fixed cell references)
- Reference tool niceties still worth carrying over on top of this dynamic model:
  - **Fee presets** — one-click buttons to apply a saved combination of charges+rates across all rows at once
  - **Per-importer fee memory** — the system remembers the last charges/rates used for a given AD Code/importer and pre-fills them next time, rather than starting blank every time
  - **Duplicate BE detection** — warns if a BE number already exists in the current batch or was previously processed, asks for confirmation before continuing
  - **Duplicate save-path/filename detection** — warns if two rows in the same batch would overwrite each other's output file

### 5.4 Charge Master

**Simplified GST treatment (per client correction):** most of the charge list is **reimbursement** — costs the agency pays on the client's behalf and passes through — and gets billed **under the Agency SAC (996713)** rather than each getting its own SAC code. The business's full SAC scope is confirmed below.

**Confirmed — full SAC scope for this business (from client-provided reference table):**
| SAC | Description |
|---|---|
| 996711 | Container handling services |
| 996712 | Customs House Agent services |
| 996713 | Clearing and forwarding services |
| 996719 | Other cargo and baggage handling services |

All under GST group 9967 (Supporting services in transport) → 99671 (Cargo handling services). **These 4 codes are the entire SAC universe for this business** — nothing outside this group is used, which resolves the earlier concern about Delivery Charges/Insurance potentially needing a different heading (9965, 997xxx, etc.) — client has confirmed everything stays within this group.

**Confirmed mapping:**
- **Container Handling → 996711**
- **All reimbursement-type charges (Customs Duty, Stamp Duty, Bond Charges, CFS Charges, Documentation, Delivery, Insurance, Other, Registration, Shipping Line, Examination, etc.) → 996713 (Agency SAC)**
- **996712 (Customs House Agent services) and 996719 (Other cargo and baggage handling) are part of the confirmed SAC family but not currently assigned to a specific charge line** — available for future use if a charge needs to be split out, but no open action item here; not a blocker.

**Charge list, final treatment:**
| Charge | Code | SAC |
|---|---|---|
| Agency Charges | AC | **996713** |
| Container Handling *(maps to Terminal Charges, Yard Charges, and/or Empty Lift On/Off — whichever line item(s) represent physical container handling; can reasonably default ALL of TC/YARD/LOLO to 996711 since they're all handling-type charges, unless client wants to split)* | TC / YARD / LOLO | **996711** |
| Bond Charges | SBOND | 996713 |
| Bond Charges (Reimbursement) | BONDC | 996713 |
| CFS Charges | CFS | 996713 |
| Customs Duty | CD | 996713 |
| Customs Duty Balance | CDB | 996713 |
| Delivery Charges | DELIVERYCHARGE | 996713 |
| Documentation Charges | DC | 996713 |
| Examination Charges | EC | 996713 |
| Insurance Charges | INS | 996713 |
| Other Charges | OTHERCHARGES | 996713 |
| Registration Charges | RC | 996713 |
| Shipping Line Charges | DO | 996713 |
| Stamp Duty | SD | 996713 |

**GST rate:** 18% throughout (9% CGST + 9% SGST intra-Maharashtra, 18% IGST inter-state) on whichever SAC applies — this entire structure is fully resolved, no open items remain on the charge master.

**Required interface:** a dedicated charge master management screen — create new charge types, set/edit SAC code (constrained to the 4-code family above, but not hard-locked in the data model in case a 5th SAC is needed later), GST rate, and default rate/calculation basis (flat / per-container / per-kg, per the three patterns already used in the reference tool — see §5.6). Charges selectable when building a proforma line-by-line.

**Reconciliation note:** this CSV list (client's actual billing-system export) is the authoritative charge master — it's broader than the charge set in the reference `be_expense_sheet.py` tool (§5.6), which only handles Agency/Other/Exam/Bond/Doc/CFS/Insurance/Royalty/Bill-Rate-HSS. The new charge master should be built from this CSV list as the base, with the reference tool's calculation-basis patterns (flat / per-container / per-kg) applied to whichever of these new charges need a non-flat basis.

### 5.5 Final Billing — **scope decision pending**
- **Filename pattern confirmed:** final bill uses the **same naming pattern as the proforma** (§5.1/§5.6: `{Importer Name} - {MBL} - {BE Number} - expense sheet.xlsm`-style pattern), once this module is built.
- **Open scope question:** client currently does final billing through a separate system, **LiveImpex**, not through this reference tool. It's not yet decided whether final billing (as described in §5.5's original scope — generate final bill, move shipment to archive, reversible if cancelled) will be built into this ERP at all, or whether the ERP stops at proforma generation and hands off to LiveImpex for the actual bill.
- **v1 recommendation:** build the **Proforma module fully** (extraction, versioning, interactive editing, charge master). Treat **final billing as a V1.5/Phase 2 decision** — build the shipment-status hook (`Billed` status + archive/un-archive behavior) now since it's cheap and doesn't depend on where the bill document itself gets generated, but hold off on building a full "generate final bill" document engine until it's confirmed whether that lives here or stays in LiveImpex.
- **[OPEN]** — Confirm with client whether/when final billing should move into this system, or if a LiveImpex integration (e.g. pushing finalized proforma data to LiveImpex via API/export) is preferred instead of duplicating billing logic.

### 5.6 Reference Implementation Notes (from `be_expense_sheet.py` v7.2)
This existing tool is the direct source of truth for Module 3's **extraction and calculation** logic, and the client is "very happy" with that engine — port it faithfully. Two things do NOT carry over as-is, both corrected elsewhere in this spec: the UI (see §1) and the **fixed-row/fixed-cell charge layout** (see §5.3's correction — charge selection must become dynamic, which also means the output document can't just mirror the template's fixed cell structure; see below).
- **Output document:** the reference tool generates from a template file (`Clarus_Logistics_Proforma_Invoice_flexible.xlsm`, provided) — a single-sheet invoice where each charge type has a **fixed, hardcoded cell** (e.g. Agency is always `C21`, CFS Rate is always `C30`) and formulas (subtotal/GST/total) reference those fixed cells directly. **The web app should reproduce this invoice's visual style/branding/layout** (see the uploaded `.xlsm` for look and feel — header, footer, fonts, the overall "shape" of the document) **but NOT its fixed-cell charge structure** — per §5.3, the new version needs a dynamic line-items table that can hold any number of charges from the charge master, with subtotal/GST/total calculated programmatically rather than off fixed cell formulas. This is the one place where the reference tool's implementation approach should be replaced rather than ported, even though its visual output is the target to match.
- **Config/memory that should carry over:** organization repository (AD Code → name lookup, updatable), per-importer fee memory (keyed by AD Code, falling back to importer name), fee presets, last-used save folder.
- **Validation behaviors worth keeping:** CFS before-tax + GST vs after-tax sanity check; duplicate BE detection (within-batch and against processing history); duplicate output-path detection.
- **Processing log:** every generated output is logged (date, importer, BE no/date, port, MBL, save path) — equivalent to an audit trail; should map onto the ERP's general version-history requirement (§2.4) rather than being a separate log.
- Not relevant to the web app (Windows-desktop-specific plumbing, safe to drop): Tkinter UI code itself, Windows Trusted Location registry handling, PyInstaller/frozen-app path resolution, the "code override" hot-patch mechanism, Zone.Identifier stripping. These solve problems specific to distributing a desktop .exe and don't apply to a web app.

---

## 6. Outstanding Items — Status at Handoff

Everything not listed below is confirmed and build-ready. This is the honest remaining gap list as of handoff:

| # | Item | Impact if left unresolved | Suggested default if building now |
|---|---|---|---|
| 1 | Full doc-type → tracker-field auto-update mapping beyond OOC (§3.3) — e.g. does uploading a Duty Challan set `Duty Paid? = Yes`? Does a DO Letter set `DO? = Yes`? | Low — pattern is obvious from the OOC example | Apply the same pattern to every Yes/No flag field in §2.2 whose name matches an existing doc type (Duty Paid?, CFS Inv?, OOC?, DO?) — build it, confirm with client after |
| 2 | Exact document-type abbreviation/token per doc type in filenames (§3.2) — is Packing List always "PL"? | Low-medium — naming will work but abbreviations may not match client's existing convention exactly | Use sensible 2-4 letter abbreviations per doc type from §3.1's list; client's 2 existing Python scripts (not yet shared) are the ground truth if precision matters before launch |
| 3 | Detailed permission matrix per role beyond Admin vs. non-admin (§2.4) — e.g. can Export Manager edit Import shipments? | Low — reasonable default below is a safe starting point | All non-admin roles: full view/add access scoped to their assigned port(s); delete requires admin approval; Accountant is the only role with Proforma & Billing module access by default (independently toggleable per user) |
| 4 | Which specific charge(s) — Terminal / Yard / Empty Lift On/Off — map to "Container Handling" SAC 996711 vs. staying under Agency 996713 (§5.4) | Low-medium — a GST/compliance detail, not a build blocker | Default ALL of Terminal, Yard, and Empty Lift On/Off to 996711 (they're all physically container-handling charges); easy to reassign individually later since SAC is a per-charge field, not hardcoded logic |
| 5 | ICEGATE/CFS portal scraping specifics (§4) | None for v1 — explicitly Phase 2, not needed to build v1 at all | N/A — skip entirely for v1 |
| 6 | LiveImpex integration decision (§5.5) — does final billing move into this system, stay external, or get an export/API bridge? | None for v1 — explicitly deferred | Build the `Billed` status + archive/un-archive hook only; do not build a full final-bill document generator yet |

**None of the above should block starting the build.** Items 1-4 have safe, clearly-stated defaults that can be built now and adjusted later with minimal rework (they're all config/data, not architecture). Items 5-6 are explicitly out of v1 scope.

---

## 7. Tech Notes (implied by requirements, to confirm with build team)
- PDF parsing: `pdfplumber` (confirmed in use today — extraction patterns in §5.1 should port directly)
- Excel parsing/writing: `openpyxl` (confirmed) — needed both for daily duty challan ingestion and for generating the invoice output; reference `.xlsm` template (`Clarus_Logistics_Proforma_Invoice_flexible.xlsm`, uploaded) defines the exact invoice layout/formula structure to reproduce
- Browser automation: Playwright — **v1 scope limited to one scheduled job** (daily duty challan pull, every morning); ICEGATE/CFS portal scraping is Phase 2
- Needs: file storage system with structured/renamed file retrieval, role-based access control (Admin vs non-admin, delete-approval workflow), port-based data scoping, **audit/version history log on all record changes** (reference tool's CSV processing log is the precedent to generalize from), versioned document storage (for proforma history), permission-gated module access (Proforma & Billing module specifically)
- Reference tool (`be_expense_sheet.py` v7.2, uploaded) is the authoritative source for Module 3's business logic — see §5.6 for what carries over vs. what's desktop-specific plumbing to drop

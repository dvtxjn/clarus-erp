# Launch checklist (one page — work top to bottom)

Rule: one phase per Claude Code session. Commit before and after. Never start Part B before every box below is ticked.

## Paste this into Claude Code for each step (change N)

```
Read PROGRESS.md and DEPLOYMENT_PLAN.md (start with "START HERE"). Do Phase N only, Fast Track scope, following the Golden Rules.
Write the tests first, then the code. Stop when "Done when" passes and tell me exactly what I should click to check it. Then update PROGRESS.md and the phase tracker, and commit.
```

## Ask the client TODAY (these are the slow part)

- [ ] H1: Dynadot auto-renew + 2FA on
- [ ] H2: Render account created in the client's name, you added as member
- [ ] H3: Shared Drive `Clarus ERP` created
- [ ] H4: Google Cloud project, Drive API, service account, key JSON, added to the Shared Drive
- [ ] H5: folders `Documents`, `Invoices`, `Backups` created; folder IDs noted
- [ ] H8: 3-5 real redacted PDFs (BE, CFS, shipping line)
- [ ] Backup encryption key saved in a password manager (not Drive)

## Build order

| # | Phase | Model | Checked by you |
|---|---|---|---|
| 1 | 0 Postgres + data move | any | [ ] shipment counts match; 3 shipments open |
| 2 | 1 (reduced) safety rules | any | [ ] delete draft, restore it |
| 3 | 3 invoice numbering | any | [ ] double-click Issue = one number |
| 4 | 2 tracker conflicts | Opus 5.5 | [ ] two browsers, same cell, dialog appears |
| 5 | 4 (reduced) locking | Opus 5.5 | [ ] upload while colleague edits; both survive |
| 6 | 6 (reduced) tests 1-5 | Opus 5.5 | [ ] tests pass; removing a lock makes them fail |
| 7 | 7 Drive storage | any | [ ] upload lands in Drive; issued PDF saved |
| 8 | 8 (reduced) backups | any | [ ] file in Drive; restore drill passed |
| 9 | 9 production readiness | any | [ ] refuses unsafe settings; login limit works |
| 10 | 10 deploy + soft launch | any | [ ] go-live checklist in the plan fully ticked |

## Then

- [ ] Soft launch: 1-2 users, 2-3 days, Google Sheet stays as reference
- [ ] Set a cut-over date; after it the Sheet is read-only
- [ ] Accountant checks 5-10 real invoices from the app
- [ ] Within 2 weeks: weekly/monthly backup tiers, second copy outside Google

## After launch (only then)

Phase 12 -> 13 (CSV import) -> 14-15 (email + Inbox) -> 11 (e2e tests) -> 16-18 (ICEGATE jobs) -> 19 (alerts, History, exports)

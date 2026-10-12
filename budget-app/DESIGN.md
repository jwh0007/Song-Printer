# Budget App — Design Draft v0.2

Status: **draft v0.2** — core decisions made (see section 10).

---

## 1. What the current system tells us

The existing workflow (MFS workbook + Fin App `finance.db` + the Cowork `budget-import` skill) works, but most of its complexity is incidental rather than essential:

| Pain point today | Root cause | Fix in new design |
|---|---|---|
| Dual-write to `.xlsx` and `finance.db`, checksums, `dd` copy-back | Two sources of truth | Database is the only source of truth; the spreadsheet becomes an optional export |
| openpyxl strips checkboxes, formula row refs break on insert | Spreadsheet used as a database | No spreadsheet writes in the core path |
| Amazon/Sam's splits done as "header row + sub-rows" | No native split model | Transactions have 1..n **splits**; receipts have **line items** linked to splits |
| Per-bank CSV hacks (2-digit years, unquoted commas, preamble commas) | Hand-written parsing per file | **Import profiles**: detected once, saved, reused deterministically |
| `ACCOUNTED-FOR -` renaming, folder-per-store drop zones | File system used as import state | Single drop zone; files hashed and logged in `import_log` |
| Categorization rules spread across LookupTable, `categorize_item.py` and skill prose | No single rules engine | One rules table + AI fallback + learning from corrections |
| "Row 883 boundary — do not modify above" | No record of who/what set a category | Every classification records `source` (user / rule / ai) and `locked` |
| Whole workflow requires Claude to drive it step-by-step | AI is the orchestrator | App is the orchestrator; AI is a service it calls |

The v2 normalized schema (`transactions`, `classifications`, `categories`, `vendor_rules`, `transfer_links`, `budget_plan`, `import_log`) is already pointed in the right direction and is the starting point here.

---

## 2. Goals

1. **Importing takes under a minute.** Drop files (CSV, OFX/QFX, PDF, receipt photo/screenshot); review only what the system is unsure about.
2. **AI-native, not AI-dependent.** Every AI feature has a deterministic path underneath; the app is fully usable with AI turned off.
3. **Model agnostic.** Swap Claude / GPT / Gemini / a local model per task via config. No provider-specific logic outside one adapter layer.
4. **Two-person household.** John and Ariel share one login; accounts still carry an owner (John / Ariel / joint).
5. **Keep all history.** Migrate every year of existing data with categories intact.

Non-goals (for v1): investment tracking, tax prep, multi-household SaaS.

---

## 3. Architecture

```
┌────────────────────────────────────────────────────────────┐
│ Web UI (desktop + phone browser)                           │
│  Inbox/Review · Transactions · Budget · Receipts · Ask     │
└──────────────┬─────────────────────────────────────────────┘
               │ REST/JSON
┌──────────────▼─────────────────────────────────────────────┐
│ API server                                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Importers│ │ Matching │ │ Rules    │ │ Analysis      │  │
│  │ +profiles│ │ engine   │ │ engine   │ │ (queries)     │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬────────┘  │
│       └────────────┴──────┬─────┴──────────────┘           │
│                    ┌──────▼──────┐                         │
│                    │ AI Gateway  │── Anthropic / OpenAI /  │
│                    │ (tasks)     │   Gemini / Ollama       │
│                    └─────────────┘                         │
│  MCP server (same API, exposed as tools for Claude/Cowork) │
└──────────────┬─────────────────────────────────────────────┘
               │
         SQLite (single file, WAL)  +  /files (originals)
```

### Stack (decided)
- **Backend:** Python + FastAPI + SQLAlchemy + SQLite. Reuses the existing Python importers.
- **Frontend:** SvelteKit (static build served by FastAPI), mobile-responsive, installable as a PWA so receipt photos can be taken from a phone.
- **Host:** an always-on Mac mini at home. Reached from phones/laptops anywhere over **Tailscale**; nothing exposed to the public internet.
- **Deploy:** code lives in a GitHub repo; the Mac mini runs `git pull` + a restart script (launchd service). The database and original statement files live only on the Mac mini, never in git.
- **Auth:** one shared household login (John and Ariel), on top of Tailscale's device-level access. Audit log records `user | rule | ai`, not which person.
- **Backups:** nightly SQLite `.backup` to a dated file, plus Time Machine.

---

## 4. Data model (core)

```
accounts          id, name, owner (john|ariel|joint), type, institution, last4
import_files      id, sha256, filename, profile_id, imported_at, row_count, status
import_profiles   id, name, match_signature, column_map(json), date_format,
                  amount_rule, quirks(json), created_by (user|ai)
transactions      id, account_id, posted_at, amount, description_raw,
                  merchant_id, external_id, raw_hash, import_file_id, status
splits            id, transaction_id, amount, category_id, note,
                  source (user|rule|ai|receipt), confidence, locked
merchants         id, display_name, patterns(json), default_category_id
categories        id, name, parent_id, kind (expense|income|saving|transfer)
rules             id, priority, conditions(json), actions(json), origin (user|learned)
transfer_links    txn_a, txn_b, kind (cc_payment|internal|venmo_cashout)
receipts          id, store, purchased_at, subtotal, tax, total, source_file_id,
                  matched_transaction_id, match_confidence
line_items        id, receipt_id, name, qty, unit_price, tax_alloc,
                  item_category, split_id
budgets           id, period_type (monthly|biweekly), category_id, amount, effective_from
ai_calls          id, task, provider, model, prompt_hash, tokens, cost, latency, ok
audit_log         id, entity, entity_id, field, old, new, actor, at
```

Key decisions embedded here:
- **Splits replace header/sub-rows.** A plain transaction has one split. Amazon order with 4 items in 3 categories → 3 splits, each linked to its line items.
- **`locked` replaces the "row 883 boundary."** Anything a person set is locked; automation never overwrites it.
- **`audit_log`** makes every automated change reviewable and undoable.

---

## 5. Import pipeline

```
file/feed → fingerprint (sha256, skip if seen)
          → detect profile (header signature match)
              └ unknown? → AI proposes column map → user confirms once → saved profile
          → normalize (dates, sign convention, encoding, quirk repairs)
          → dedupe (external_id, else raw_hash of date+amount+desc+account)
          → transfer detection (CC payment ↔ checking withdrawal, internal transfers)
          → merchant resolution (pattern table → AI fallback)
          → categorization (rules → merchant default → AI with confidence)
          → receipt matching (if receipts available)
          → Inbox: only rows below confidence threshold or flagged
```

**Bank connection (decided): files only.** No aggregator (SimpleFIN/Plaid). The import step itself must therefore be fast:
- One drop zone (web upload, phone share sheet, and a watched folder on the Mac mini).
- Profiles for each known source, built in from day one:

| Source | Accounts | Format |
|---|---|---|
| Redstone FCU checking | 2 | CSV (Transaction Number, Date, Description, Memo, Debit, Credit, …) |
| Robinhood credit card | 1 | CSV / statement export (profile to be captured from a sample) |
| Venmo | 2 (John, Ariel) | Statement CSV, header on row 3 |
| PayPal | 1 | Activity CSV |
| Amazon / Target / Walmart / Lowe's / Home Depot / Sam's | — | Order-history CSV, PDF, receipt photo |

- Per-account "last imported through" date shown on the dashboard, so it's obvious what needs downloading.

Note: the existing skill describes the credit card CSV as `Post Date, Description, Category, Reference Number, Amount`. Confirm whether that is the Robinhood card or a previous card.

**Receipts & orders:** keep the existing order-history scraper extension, but have it POST straight to the app instead of downloading a CSV. Photos/PDFs go through the AI `extract_receipt` task.

**Deleted-on-purpose rows:** deleting a transaction tombstones its `raw_hash` so re-imports never resurrect it.

---

## 6. AI layer (model agnostic)

### 6.1 Gateway
A single internal interface:

```python
class LLMProvider(Protocol):
    def complete(self, messages, *, schema=None, tools=None, images=None) -> Result
```

Adapters: Anthropic, OpenAI, Google, OpenAI-compatible (covers Ollama, LM Studio, OpenRouter). Configuration is per **task**, not global:

```yaml
tasks:
  categorize:       { provider: ollama,    model: qwen3:14b,     fallback: anthropic/claude-haiku-5-5 }
  extract_receipt:  { provider: anthropic, model: claude-sonnet-5-5 }
  map_csv_profile:  { provider: anthropic, model: claude-haiku-5-5 }
  analyze:          { provider: anthropic, model: claude-opus-5-5 }
```

### 6.2 Tasks are defined, not improvised
Each AI task = prompt template + JSON output schema + validator + deterministic fallback.

| Task | Input | Output | Fallback without AI |
|---|---|---|---|
| `map_csv_profile` | header + 10 sample rows | column map, date format, sign rule | manual mapping form |
| `resolve_merchant` | raw description | display name | pattern table / raw text |
| `categorize` | txn + merchant + few-shot examples from own history | category, confidence, reason | rules only, rest → Inbox |
| `extract_receipt` | image/PDF | store, date, items, tax, total | manual entry |
| `categorize_items` | line items | item + budget category | keyword table (`categorize_item.py`) |
| `propose_rule` | a user correction + similar txns | rule suggestion | none |
| `analyze` | question | answer + the queries used | prebuilt reports |

### 6.3 Analysis uses tools, not data dumps
The `analyze` task gets **read-only tools** (`query_spending`, `list_transactions`, `budget_vs_actual`, `run_sql` on a read-only connection) rather than a CSV pasted into the prompt. Answers show the queries behind them so numbers can be checked.

### 6.4 Learning from corrections
When a user re-categorizes, the app (1) locks that split, (2) adds it to the few-shot example pool, (3) if ≥N similar transactions exist, offers a rule: *"Always categorize KROGER FUEL as Transportation › Gas?"*

### 6.5 Evaluation harness
Years of hand-categorized history are a labeled dataset. `eval` command replays a hold-out set through any provider/model and reports accuracy, cost and latency per task. This is what makes "model agnostic" practical: choose models on measured results, re-test when new models ship.

### 6.6 Privacy controls (decided)
- Cloud providers are allowed for all tasks.
- Account numbers, card numbers and masked digits (`XXXX1234`, `*1234`) are redacted before any AI call.
- Per-task "local only" flag remains available but off by default.
- `ai_calls` log records what was sent where.

---

## 7. UI — main screens

1. **Inbox** — the only screen needed after an import. Cards for low-confidence items with AI suggestion + one-tap accept / change / split. Keyboard-driven on desktop, swipe on phone.
2. **Transactions** — fast filterable table; inline edit; split editor; linked receipt view.
3. **Budget** — monthly and biweekly (paycheck-period) views, matching the workbook's Budget and Biweekly Budget tabs; budget vs actual. No envelope/rollover model.
4. **Receipts** — upload/photo, extracted items, match status.
5. **Ask** — chat over the data with cited queries; saved questions become dashboard tiles.
6. **Insights** (generated after each import) — month summary, anomalies, new/changed subscriptions, price changes on repeat items.
7. **Settings** — accounts, categories, rules, import profiles, AI providers per task.

---

## 8. Migration

**The MFS workbook is the source of truth** (it is ahead of `finance.db`). The database is used only to fill gaps and cross-check.

1. Load categories tree from LookupTable E/F map (keeping the "Reccreation" spelling or fixing it — to confirm).
2. Import every year's Expense Tracker as locked splits; convert Amazon/receipt header + sub-row groups into multi-split transactions.
3. Compare against `finance.db`; report rows present only in the DB rather than importing them silently.
4. Import Itemized Purchases → receipts + line items, re-link to splits.
5. Import LookupTable merchant rows → `merchants` + `rules`.
6. Reconciliation report: per-year totals by category, old vs new, must match to the cent.

---

## 9. Build phases

| Phase | Scope | Done when |
|---|---|---|
| 0 | Repo, schema, migration from the MFS workbook | Totals reconcile with workbook for every year |
| 1 | File import + profiles + dedupe + transfers + rules | A month of statements imports with no manual CSV editing |
| 2 | AI gateway + `categorize` + Inbox + eval harness | ≥90% auto-categorized on hold-out, measured |
| 3 | Receipts: extraction, matching, splits | Amazon/Target/Walmart orders auto-split |
| 4 | Budget views + Ask + Insights | Replaces the Dashboard/Biweekly tabs |
| 5 | MCP server, phone PWA polish | Optional extras |

---

## 10. Decisions log

| # | Question | Decision |
|---|---|---|
| 1 | Where code lives / runs | New GitHub repo; runs on a home Mac mini, deployed by `git pull` |
| 2 | Remote access | Tailscale; no public exposure |
| 3 | Bank feed | Files only (Redstone ×2, Robinhood card, Venmo ×2, PayPal) |
| 4 | Users | John and Ariel, one shared login |
| 5 | Migration source | MFS workbook is primary; `finance.db` for cross-check only |
| 6 | Budget model | Keep monthly + biweekly category budgets |
| 7 | AI privacy | Cloud models allowed; redact account/card numbers |
| 8 | Frontend | SvelteKit |

## 11. Still open

1. Name of the new repo (to be created on GitHub).
2. Is the `Post Date, Description, Category, Reference Number, Amount` CSV the Robinhood card? A sample export of each source (with numbers redacted) is needed to build the import profiles.
3. Fix the "Reccreation" spelling during migration, or keep it?

# Budget App — Design Draft v0.1

Status: **draft for discussion**. Sections marked **[DECIDE]** need input before build.

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

1. **Importing takes under a minute.** Drop files (CSV, OFX/QFX, PDF, receipt photo/screenshot) or pull from a bank feed; review only what the system is unsure about.
2. **AI-native, not AI-dependent.** Every AI feature has a deterministic path underneath; the app is fully usable with AI turned off.
3. **Model agnostic.** Swap Claude / GPT / Gemini / a local model per task via config. No provider-specific logic outside one adapter layer.
4. **Two-person household.** John and Ariel, their own accounts (Venmo, PayPal), shared budget.
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

### Proposed stack **[DECIDE]**
- **Backend:** Python + FastAPI + SQLAlchemy + SQLite. Reuses the existing Python importers and the user's familiarity.
- **Frontend:** SvelteKit or React (Vite) SPA, mobile-responsive. Installable as a PWA so receipt photos can be taken from a phone.
- **Hosting options:**
  - (a) Local on the Mac, reachable on home Wi-Fi — simplest, most private, phone works only at home.
  - (b) Small VPS / home server behind Tailscale — phone works anywhere, still private.
  - (c) Managed cloud (Fly.io/Render + Postgres) — most convenient, most exposure.
  - Recommendation: build for (a), keep (b) a config change away.

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

**Bank connection [DECIDE]:**
- File import only (current approach, zero cost, zero third-party).
- **SimpleFIN Bridge** (~$15/yr, read-only, privacy-focused, works with many US banks).
- Plaid (broadest coverage, more setup, developer account required).
- Recommendation: file import in v1, SimpleFIN as the first feed adapter.

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

### 6.6 Privacy controls
- Per-task "local only" flag.
- Redaction before sending: account numbers, names in Venmo notes (optional).
- `ai_calls` log records what was sent where.

---

## 7. UI — main screens

1. **Inbox** — the only screen needed after an import. Cards for low-confidence items with AI suggestion + one-tap accept / change / split. Keyboard-driven on desktop, swipe on phone.
2. **Transactions** — fast filterable table; inline edit; split editor; linked receipt view.
3. **Budget** — monthly and biweekly views (current workbook has both), budget vs actual, rollover.
4. **Receipts** — upload/photo, extracted items, match status.
5. **Ask** — chat over the data with cited queries; saved questions become dashboard tiles.
6. **Insights** (generated after each import) — month summary, anomalies, new/changed subscriptions, price changes on repeat items.
7. **Settings** — accounts, categories, rules, import profiles, AI providers per task.

---

## 8. Migration

1. Load categories tree from LookupTable E/F map (deduplicate the duplicate leaf names noted in v2).
2. Import `finance.db` v2 transactions/classifications as locked splits.
3. Import workbook Expense Trackers for any years missing from the DB; convert header/sub-row groups into splits.
4. Import Itemized Purchases → receipts + line items, re-link to splits.
5. Import LookupTable merchant rows → `merchants` + `rules`.
6. Reconciliation report: per-year totals by category, old vs new, must match to the cent.

---

## 9. Build phases

| Phase | Scope | Done when |
|---|---|---|
| 0 | Repo, schema, migration from current data | Totals reconcile with workbook for every year |
| 1 | File import + profiles + dedupe + transfers + rules | A month of statements imports with no manual CSV editing |
| 2 | AI gateway + `categorize` + Inbox + eval harness | ≥90% auto-categorized on hold-out, measured |
| 3 | Receipts: extraction, matching, splits | Amazon/Target/Walmart orders auto-split |
| 4 | Budget views + Ask + Insights | Replaces the Dashboard/Biweekly tabs |
| 5 | MCP server, phone PWA, bank feed | Optional extras |

---

## 10. Open questions

1. **Repo location.** This draft sits on a branch of `Song-Printer`. Recommendation: a new dedicated repo.
2. **Hosting:** local Mac vs. private server vs. cloud (section 3).
3. **Bank feed:** files only vs. SimpleFIN vs. Plaid (section 5).
4. **Users:** Does Ariel use the app directly (separate login, phone access) or is it John-operated?
5. **Source of truth for migration:** Is `finance.db` v2 current and complete, or is the workbook ahead of it?
6. **Budget model:** Keep monthly + biweekly category budgets as-is, or consider envelope/zero-based?
7. **AI privacy line:** Is sending transaction descriptions to cloud providers acceptable, or should categorization default to a local model?
8. **Frontend preference:** any preference between Svelte and React, or none?

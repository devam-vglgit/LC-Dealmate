# LC DealMate

An AI negotiation agent for software and vendor spend. Ask it about the tools the
company pays for, and it benchmarks them against live competitor pricing and tells you
whether to renew, renegotiate, switch, or consolidate.

```
┌─────────────┐    SSE     ┌──────────────┐   web_search   ┌──────────┐
│  React UI   │ ◀────────▶ │   FastAPI    │ ◀────────────▶ │  Claude  │
│  (Vite)     │  /api/chat │              │                │  Opus 5  │
└─────────────┘            └──────┬───────┘                └──────────┘
                                  │
                        software_inventory.json
```

The inventory is injected into every request as system-prompt context, so the agent
always answers against what the company actually pays for. Competitor pricing comes from
Claude's server-side `web_search` tool at query time — no separate search API key, and
prices are never answered from the model's memory.

---

## Setup

Run everything from the project root.

**1. Backend** — create the virtualenv, then install into it:

```
python -m venv backend\.venv
```

```
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Create `backend\.env` (copy `.env.example`) and add your key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

**2. Frontend**

```
npm --prefix frontend install
```

## Running

Two terminals, both opened at the project root. These avoid `&&` and `cd` so they work
in PowerShell as well as bash.

Terminal 1 — backend on :8000

```
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8000 --reload
```

Terminal 2 — frontend on :5173

```
npm --prefix frontend run dev
```

Open http://localhost:5173. Vite proxies `/api` to port 8000, so both must be running.
`Ctrl+C` stops either.

`GET /api/health` reports whether credentials resolved — check it first if chat errors.

---

## Loading the real inventory

Replace the `software` array in `backend/data/software_inventory.json`. It currently
holds four clearly-marked **sample rows** so the app runs before the real data exists.

The file is re-read on every request — edit it and ask the next question, no restart.

Only `vendor` and `product` are required; the agent works with whatever else is filled
in, and richer rows produce sharper recommendations.

| Field | Why the agent wants it |
|---|---|
| `vendor`, `product`, `plan` | Identifies what to benchmark against |
| `seats`, `unit_price_annual`, `annual_cost` | Computes per-seat rate and savings |
| `renewal_date` | Drives urgency and the renewal queue |
| `notice_period_days` | Derives the real deadline — the cancellation cutoff, not the renewal date |
| `auto_renew` | Whether silence costs you another year |
| `utilization_pct` | The strongest lever for a seat-reduction ask |
| `business_criticality` | How seriously to weigh switching risk |
| `owner`, `category`, `notes` | Routing and context |

Derived fields (`days_until_renewal`, `days_until_cancellation_deadline`,
`total_annual_spend`) are computed server-side in `app/inventory.py` — don't put them in
the JSON.

---

## Layout

```
backend/
  app/
    main.py        FastAPI routes; SSE framing
    agent.py       Claude streaming loop, web search, error handling
    prompts.py     System prompt — the agent's negotiation playbook
    inventory.py   Loads/enriches the inventory, renders it for the model
  data/
    software_inventory.json    ← replace this
frontend/
  src/
    App.jsx        Conversation state, streaming reducer
    api.js         SSE-over-fetch client
    components/    InventoryPanel, Message
```

To change how the agent reasons about a negotiation, edit `prompts.py` — that file, not
the code, is where the product behaviour lives.

## Configuration

Set in `backend/.env`:

| Variable | Default | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required |
| `LC_MODEL` | `claude-opus-5` | |
| `LC_EFFORT` | `high` | `low`/`medium` are cheaper and faster; worth testing |
| `LC_MAX_TOKENS` | `16000` | |
| `LC_ENABLE_FALLBACK` | `1` | Server-side fallback: if a safety classifier declines a request, the API retries it on a fallback model instead of returning the refusal. Set `0` to disable. |

---

## Scope

The agent drafts; it does not act. It has no ability to contact a vendor, sign, or
commit to anything — outbound negotiation stays a human step by design.

Pricing it surfaces is research, not a quote. Public list prices are a benchmark;
enterprise tiers are usually unpublished, and the agent is instructed to say so rather
than invent a number.

## Not built yet

- Persistence — conversations are in-memory and lost on refresh
- Auth — the API is unauthenticated; bind it to localhost or put it behind SSO before
  sharing
- Inventory upload UI — the JSON file is edited by hand today
- Renewal alerting — the panel shows the queue, but nothing emails anyone

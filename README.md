# Tessel

An evidence and explainability layer for lending/underwriting teams — not another risk score.

Tessel takes a connected life transition (a change in status, income, or documentation that
plays out over months) and produces a traceable answer to one question: **what happened, what
evidence supports it, what's still unresolved, and what would resolve it.** No score, no black
box — every conclusion links back to the deterministic check, retrieval match, LLM call, or
human decision that produced it.

## The problem

Lenders typically evaluate financial signals in isolation: an income gap here, an incoming
transfer there, a status change somewhere else — each scored independently, with no model of
how they connect. Someone whose income paused because of a documented, time-boxed, authorized
interruption (a work-authorization renewal, a leave, a severance period) looks identical to
someone whose income just stopped, unless the system can connect the two facts and check
whether the connection actually holds up against evidence.

Tessel connects them.

## How it works

Four stages, escalating in cost only when they need to:

```
Timeline data  →  Deterministic rules  →  RAG evidence match  →  LLM escalation  →  Audit trail
(Plaid, docs)     (dates, certainty)      (does the doc          (only for genuinely   (every stage
                                           match the claim?)       ambiguous cases)      logs itself)
```

1. **Deterministic rules** resolve what's certain. Do an income gap's dates align with a
   documented authorized interruption? Did an incoming transfer land inside that gap? Pure
   date/amount logic — no model involved, and most cases resolve here.
2. **RAG evidence matching** (local `sentence-transformers` embeddings, no API cost) checks
   whether an uploaded document's content actually supports the claim it's attached to — a
   keyword check catches clear contradictions before similarity scoring even runs.
3. **LLM escalation** only fires for what's left genuinely ambiguous after 1 and 2. Claude is
   given the exact structured records involved and forced through a single schema-constrained
   tool call — it can't return free text, and it can't see anything the rules didn't already
   surface.
4. **Audit trail**: every rule check, retrieval match, LLM call, and human decision is written
   as an append-only entry — timestamped, linked to what it evaluated, never edited after the
   fact.

## The MVP scenario: F-1 → OPT

The first (and currently only) populated instance of this pattern is the F-1 student → OPT
work-authorization transition:

- **Authorized-interruption alignment** — does an income gap's timing match a documented,
  evidence-backed pending work-authorization status?
- **Remittance plausibility** — did an international transfer arrive during that gap in a
  pattern consistent with family support while income paused?

F-1/OPT is the proof case, not an assumption baked into the schema — the category the rule
engine reasons over (`AUTHORIZED_INTERRUPTION`) is generic on purpose, so a different
interruption (parental leave, a severance period, a contractor transition) is a new entry in
that category, not a rewrite.

## Stack

| Layer | Tech | Why |
|---|---|---|
| API + data model | FastAPI + SQLAlchemy/SQLite | Simple, typed, no infra to stand up for a prototype |
| Bank data | Plaid (Sandbox) | Real transaction data, not fabricated income events |
| Evidence matching | `sentence-transformers` (`all-MiniLM-L6-v2`) | Local, free, good enough for document-vs-claim similarity |
| Ambiguous-case reasoning | Claude API, forced tool use | Structured, auditable output — never free-text judgment |
| UI | Server-rendered Jinja2 | One evidence-trail page and a case queue; no SPA needed yet |

## Running it locally

**Requirements:** Python 3.11+, a [Plaid Sandbox](https://dashboard.plaid.com) account, and
(optionally, for real LLM escalation instead of the graceful fallback) an Anthropic API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` in the repo root:

```
PLAID_CLIENT_ID=your_client_id
PLAID_SECRET=your_sandbox_secret
PLAID_ENV=sandbox
ANTHROPIC_API_KEY=your_key          # optional — omit to see the fallback path instead
```

Seed one demo applicant end-to-end against real services (Plaid ingestion, RAG match, rule
engine, LLM escalation):

```bash
python scripts/seed_demo_applicant.py
```

Then run the app:

```bash
uvicorn app.main:app --reload
```

- `http://localhost:8000/` — case queue
- `http://localhost:8000/applicants/1/evidence-trail` — the seeded demo case

## What's not here yet

Deliberately deferred, not forgotten: an applicant-facing document upload flow (evidence
currently arrives via the seed script), and one-click PDF export of the evidence trail. Both
are real product value, both are bigger lifts than anything currently built, and neither was
worth trading against the core mechanism working end-to-end on real data first.

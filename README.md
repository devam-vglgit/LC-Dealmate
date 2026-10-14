# LC DealMate

Read-only AI advisor for ShopLC CMS contracts. It runs **inside CMS** (iframe
or reverse-proxy), loads the live Postgres portfolio, streams PDFs to the
browser only, and chats with Claude about pricing and alternatives.

```
CMS  --JWT+contract id-->  DealMate SPA + FastAPI
                                |  DATABASE_URL → CMS Postgres
                                |  Azure Blob   → PDF to browser (never to the model)
                                └─ Claude + web_search
```

DealMate cannot add, edit, or delete contracts. There is no local inventory
file and no document upload.

---

## Run with CMS (UAT)

1. Copy `backend/.env.example` to `backend/.env`. Set `ANTHROPIC_API_KEY`,
   `CMS_EMBED_SECRET` (same value CMS will sign with), `DATABASE_URL` pointing
   at `cms-uat-postgres-uat-1`, and the Azure / encryption keys CMS already uses.
2. Join the CMS network and build:

```
docker compose up --build
```

`DATABASE_URL` in `.env` should look like:

```
DATABASE_URL=postgresql://cms_app_uat:PASSWORD@cms-uat-postgres-uat-1:5432/cms_uat
```

Open DealMate at `http://localhost:8101` (SPA served by FastAPI). Chat history
and the CMS snapshot persist in the `dealmate-data` volume. CMS should iframe
that origin (or a reverse-proxied path) with a token:

```
https://<dealmate>/?token=<jwt>&contract=<uuid>
```

### JWT CMS must mint

HS256, same secret as `CMS_EMBED_SECRET` (or `SSO_JWT_SECRET`):

```js
jwt.sign({ sub: user.username }, process.env.CMS_EMBED_SECRET, {
  algorithm: 'HS256',
  expiresIn: '12h',
})
```

DealMate exchanges that JWT for its own session. `contract` is optional — when
present, that row opens in the dashboard.

CSP `frame-ancestors` already allows `https://contractsuat.shoplc.com`,
`https://contracts.shoplc.com`, and `http://localhost:38090`. Override with
`LC_FRAME_ANCESTORS` if needed.

---

## Local development (without Docker)

Two terminals from the repo root. Backend listens on **8101** (Vite proxies `/api`).

```
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --port 8101 --reload
```

```
npm --prefix frontend install
npm --prefix frontend run dev
```

Open http://localhost:5173. If `DATABASE_URL` is unset, DealMate falls back to
`docker exec` into `cms-uat-postgres-uat-1` so Windows Docker Desktop still
works. `GET /api/health` reports `cms.connected`, `cms_handoff`, and
`sends_contracts_to_model`.

Optional local login: set `LC_AUTH_USERNAME` / `LC_AUTH_PASSWORD`. When those
are blank and `CMS_EMBED_SECRET` is set, the only sign-in is the CMS JWT.

---

## What reaches the model

Governed by `LC_SEND_CONTRACTS_TO_MODEL` (default `0`). Health reports the live
value as `sends_contracts_to_model`.

| Setting | Model sees |
|---|---|
| `0` | Nothing from CMS. General pricing questions only. |
| `1` | De-identified contract rows (`app/redact.py`) plus a short CMS excerpt for the open contract. |

Never sent, at either setting: PDFs, full document text, ShopLC identity,
`SLCI-VA-…` codes, individual people's names (shown as `[an individual contractor]`).

PDFs are decrypted and streamed to **this browser** via
`GET /api/cms/contracts/{id}/document`.

Request Anthropic Zero Data Retention before turning the flag on.

---

## Layout

```
backend/app/
  main.py         API, CMS JWT exchange, SPA in production
  auth.py         Local login + CMS HS256 handoff
  cms.py          Portfolio from Postgres
  cms_db.py       DATABASE_URL, then optional docker-exec fallback
  cms_files.py    Azure Blob decrypt → browser
  inventory.py    Shapes CMS rows; redacted blocks for the model
  redact.py       Outbound allowlist
  agent.py        Claude streaming + web_search
  prompts.py      Negotiation playbook
frontend/src/     React SPA (embed + ?contract=)
```

Edit `prompts.py` to change how the agent answers. The model is read-only: it
cannot change CMS.

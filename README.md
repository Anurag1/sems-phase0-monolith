
---

# `README.md`

# 🚀 Phase-0 Monolith (SEMS)

This project is a **single production-ready monolith** that integrates:

* **Inference Adapter (Proxy)**
* **Registry (Postgres + pgvector)**
* **Binder** (atomic tokens & prompt rewriting)
* **Memory System** (Hot / Warm / Cold tiers, PCA compression, clustering, centroids)
* **Base Evolution Engine (BEE)** (pattern discovery → proposals)
* **Governance** (auditable approval workflow → promote proposals into new atoms)
* **Merkle provenance** for tamper-evident interactions

Everything runs in **one FastAPI app** with **Postgres** as the single datastore.

---

## ⚙️ Quickstart

### 1. Clone & prepare

```bash
git clone <this-repo> sems-phase0-monolith
cd sems-phase0-monolith
cp .env.example .env
```

Edit `.env` to include:

* `API_KEY` (client API key for proxy requests)
* `PROVIDER_API_KEY` (your LLM/embedding provider key, e.g., OpenAI)

### 2. Build & run

```bash
docker compose up --build
```

This starts:

* `db`: Postgres + pgvector
* `app`: FastAPI monolith on `http://localhost:8080`

### 3. Seed initial atom & governance user

```bash
docker compose exec app python -m app.seed
docker compose exec app python -m app.seed_governance
```

Output:

```
seeded atom
seeded governance user alice with secret: supersecret123
```

Now you can act as:

* **Client API user** → use header `x-api-key: <API_KEY>`
* **Governance approver** → use header `x-approver-key: alice:supersecret123`

---

## 📡 API Examples

### Proxy request

```bash
curl -X POST http://localhost:8080/v1/proxy \
  -H "Content-Type: application/json" \
  -H "x-api-key: replace-with-client-api-key" \
  -d '{"prompt":"Explain for (int i=0; i<n; i++) and its pitfalls."}'
```

Response:

```json
{
  "output": "...",
  "merkle_root": "abc123...",
  "binder_used": {"rewritten": true, "token_used": {...}}
}
```

### Verify chain

```bash
curl -H "x-api-key: replace-with-client-api-key" http://localhost:8080/v1/verify_chain
```

### List proposals (BEE discoveries)

```bash
curl -H "x-api-key: replace-with-client-api-key" http://localhost:8080/v1/proposals
```

### Approve proposal

```bash
curl -X POST http://localhost:8080/v1/proposals/<proposal_id>/approve \
  -H "x-approver-key: alice:supersecret123"
```

### Reject proposal

```bash
curl -X POST http://localhost:8080/v1/proposals/<proposal_id>/reject \
  -H "x-approver-key: alice:supersecret123" \
  -H "Content-Type: application/json" \
  -d '{"reason":"unsafe pattern"}'
```

---

## 🧩 Memory System

* **Hot memory**: recent interactions with full embeddings (1536 dims).
* **Warm memory**: compressed embeddings (PCA → 256 dims).
* **Cold memory**: centroids summarizing many old interactions.

Compression, clustering, and eviction run as background jobs.

---

## 🧠 Binder & Atoms

* Looks up atomic tokens by embedding similarity.
* Rewrites prompts (`for (int i=0; i<n; i++)` → `<ATOM:ATOM_LOOP_INC>`).
* Approved proposals from BEE become new atoms in `atomic_tokens`.

---

## 🧬 Governance

* Approvers authenticate with `x-approver-key`.
* Actions (`approve`, `reject`, `needs_review`) logged in `proposal_audit_log`.
* Approved proposals promote candidates into `atomic_tokens`.
* Provenance stored (`provenance = "promoted_from:<proposal_id>"`).

---

## 📊 Observability

* Prometheus metrics at `/metrics`
* Request latency, counts, binder usage rates
* Merkle verification endpoint at `/v1/verify_chain`

---

## ✅ Post-Deploy Checklist

* [ ] Replace `API_KEY` & `PROVIDER_API_KEY` with secure values in `.env`
* [ ] Rotate approver secrets → use hashed storage (bcrypt recommended)
* [ ] Pre-fit PCA model (`pca_model.pkl`) on representative corpus and mount volume
* [ ] Add automated sandbox tests in governance approval path
* [ ] Tune clustering (replace naive chunking with FAISS/HDBSCAN)
* [ ] Configure backups for Postgres & external audit log storage
* [ ] Monitor `/metrics` in Prometheus/Grafana

---

## 🔒 Security Notes

* Governance API uses simple username\:secret → replace with JWT/OAuth2 in prod
* Approver actions should require quorum (N-of-M) in regulated settings
* Sensitive logs must be redacted before exporting
* Expose `/v1/proposals/*` only to internal networks or VPN

---

import os, asyncio, json
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from .settings import Settings
from .db import create_pool, insert_interaction, compute_merkle, get_latest_merkle, ensure_essence, append_form_history
from .memory_manager import compress_embedding, cluster_and_compact
from .binder import binder_lookup, maybe_rewrite_prompt
from .bee import bee_loop
from .governance import verify_approver, log_proposal_action
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

settings = Settings()
app = FastAPI(title="SEMS Phase0 Monolith (Generational)")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

db_pool = None
REQUEST_COUNT = Counter('sems_requests_total', 'Total proxy requests', ['status'])
REQUEST_LATENCY = Histogram('sems_request_latency_seconds', 'Latency of proxy', ['operation'])

async def provider_embedding_call(text: str):
    headers = {"Authorization": f"Bearer {settings.provider_api_key}"}
    payload = {"model": settings.embedding_model, "input": text}
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.post(settings.embedding_url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["data"][0]["embedding"]

async def provider_llm_call(prompt: str):
    headers = {"Authorization": f"Bearer {settings.provider_api_key}"}
    payload = {"model": settings.llm_model, "messages":[{"role":"user","content":prompt}]}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(settings.llm_url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()

def verify_api_key(request: Request):
    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")
    if not provided or provided != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await create_pool()
    asyncio.create_task(periodic_tasks())
    asyncio.create_task(bee_loop())

@app.on_event("shutdown")
async def shutdown():
    await db_pool.close()

@app.post("/v1/proxy", dependencies=[Depends(verify_api_key)])
@limiter.limit("100/minute")
async def proxy_endpoint(request: Request):
    body = await request.json()
    prompt = body.get("prompt") or body.get("input")
    if not prompt:
        raise HTTPException(status_code=400, detail="`prompt` required")
    with REQUEST_LATENCY.labels("total").time():
        REQUEST_COUNT.labels("in_progress").inc()
        try:
            input_emb = await provider_embedding_call(prompt)
            input_emb_c = compress_embedding(input_emb)
            async with db_pool.acquire() as conn:
                binder_candidates = await binder_lookup(conn, input_emb_c, top_k=3)
            rewritten_prompt, rewrite_meta = maybe_rewrite_prompt(prompt, binder_candidates)
            provider_resp = await provider_llm_call(rewritten_prompt)
            output_text = provider_resp["choices"][0]["message"]["content"]
            output_emb = await provider_embedding_call(output_text)
            output_emb_c = compress_embedding(output_emb)
            summary = (output_text[:512] + '...') if len(output_text) > 512 else output_text

            # determine essence_refs: collect essence_id(s) from binder candidates and rewrite metadata
            essence_refs = []
            for c in binder_candidates:
                if c.get("essence_id"):
                    essence_refs.append(c["essence_id"])
            if rewrite_meta.get("essence"):
                essence_refs.append(rewrite_meta["essence"])
            # dedupe
            essence_refs = list(dict.fromkeys([e for e in essence_refs if e]))

            merkle = await insert_interaction(db_pool, prompt, output_text, input_emb, output_emb,
                                              input_emb_c, output_emb_c, summary, [c['label'] for c in binder_candidates],
                                              essence_refs, provider_resp, {"rewrite": rewrite_meta})
            REQUEST_COUNT.labels("200").inc()
            return JSONResponse({"output": output_text, "merkle_root": merkle, "binder_used": rewrite_meta})
        except httpx.HTTPStatusError as e:
            REQUEST_COUNT.labels(str(e.response.status_code)).inc()
            raise HTTPException(status_code=502, detail="Upstream error")
        except Exception as e:
            REQUEST_COUNT.labels("500").inc()
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            REQUEST_COUNT.labels("in_progress").dec()

@app.get("/v1/proposals", dependencies=[Depends(verify_api_key)])
async def list_proposals(limit: int = 50):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT proposal_id, candidate_atoms, compression_gain, predictive_delta, causal_utility, safety_risks, status, created_at FROM rebase_proposals ORDER BY created_at DESC LIMIT $1", limit)
    return [dict(r) for r in rows]

@app.get("/v1/proposals/{proposal_id}", dependencies=[Depends(verify_api_key)])
async def get_proposal(proposal_id: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM rebase_proposals WHERE proposal_id = $1", proposal_id)
    if not row:
        raise HTTPException(status_code=404, detail="proposal not found")
    await log_proposal_action(proposal_id, "viewed", None, {"viewer": "api_user"})
    return dict(row)

@app.post("/v1/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, request: Request):
    approver_key = request.headers.get("x-approver-key")
    user = await verify_approver(approver_key)
    if not user:
        raise HTTPException(status_code=401, detail="invalid approver credentials")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM rebase_proposals WHERE proposal_id = $1", proposal_id)
        if not row:
            raise HTTPException(status_code=404, detail="proposal not found")
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="proposal not pending")
        safety = row["safety_risks"] or []
        if isinstance(safety, list) and len(safety) > 0:
            await conn.execute("UPDATE rebase_proposals SET status = 'needs_review' WHERE proposal_id = $1", proposal_id)
            await log_proposal_action(proposal_id, "marked_needs_review", user["user_id"], {"reason": "safety_risks_present"})
            raise HTTPException(status_code=400, detail="proposal has safety risks; marked for review")
        candidates = row["candidate_atoms"]
        promoted_count = 0
        for cand in candidates:
            label = cand.get("label")
            pattern = cand.get("pattern") or cand.get("base_repr") or ""
            canonical = cand.get("canonical_meaning") or pattern
            # ensure essence
            essence_id = await ensure_essence(db_pool, canonical, form=pattern, generation="G_next")
            # add form history entry for this new form
            await append_form_history(db_pool, essence_id, pattern, generation="G_next", meta={"proposal": proposal_id})
            # compute embedding for pattern if available (best-effort)
            emb = await provider_embedding_call(pattern) if pattern else [0.0]*1536
            emb_c = compress_embedding(emb)
            await conn.execute("""
                INSERT INTO atomic_tokens (essence_id, label, base_repr, meaning, embedding, embedding_compressed, provenance, trust_score)
                VALUES ($1,$2,$3,$4,$5::vector,$6::vector,$7,$8)
            """, essence_id, label, pattern, canonical, emb, emb_c, f"promoted_from:{proposal_id}", 0.8)
            promoted_count += 1
        await conn.execute("UPDATE rebase_proposals SET status='approved' WHERE proposal_id = $1", proposal_id)
        await log_proposal_action(proposal_id, "approved", user["user_id"], {"promoted_count": promoted_count})
    return {"status": "approved", "promoted": promoted_count}

@app.post("/v1/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, request: Request):
    approver_key = request.headers.get("x-approver-key")
    user = await verify_approver(approver_key)
    if not user:
        raise HTTPException(status_code=401, detail="invalid approver credentials")
    body = await request.json()
    reason = body.get("reason", "no_reason_provided")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM rebase_proposals WHERE proposal_id = $1", proposal_id)
        if not row:
            raise HTTPException(status_code=404, detail="proposal not found")
        if row["status"] not in ("pending", "needs_review"):
            raise HTTPException(status_code=400, detail="proposal cannot be rejected in current state")
        await conn.execute("UPDATE rebase_proposals SET status='rejected' WHERE proposal_id = $1", proposal_id)
        await log_proposal_action(proposal_id, "rejected", user["user_id"], {"reason": reason})
    return {"status": "rejected"}

@app.get("/v1/verify_chain", dependencies=[Depends(verify_api_key)])
async def verify_chain():
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT input_text, output_text, timestamp, merkle_root FROM interactions ORDER BY timestamp ASC")
    prev = "0"*64
    bad = []
    for r in rows:
        record = {"input": r["input_text"], "output": r["output_text"], "timestamp": r["timestamp"].isoformat()}
        recomputed = compute_merkle(prev, record)
        if recomputed != r["merkle_root"]:
            bad.append({"expected": r["merkle_root"], "recomputed": recomputed})
        prev = recomputed
    return {"valid": len(bad) == 0, "problems": bad}

@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

async def periodic_tasks():
    while True:
        try:
            await cluster_and_compact()
        except Exception as e:
            print("Compaction error", e)
        await asyncio.sleep(300)

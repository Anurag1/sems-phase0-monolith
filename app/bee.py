import asyncio
import json
import numpy as np
from collections import Counter
from .db import create_pool
from .settings import Settings

settings = Settings()

def ngrams_from_text(text, n=3):
    words = text.split()
    return [" ".join(words[i:i+n]) for i in range(max(0, len(words)-n+1))]

async def fetch_recent_texts(limit=5000):
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT input_text FROM interactions ORDER BY timestamp DESC LIMIT $1", limit)
    return [r['input_text'] or "" for r in rows]

async def discover_candidates_fallback():
    texts = await fetch_recent_texts(limit=2000)
    freq = Counter()
    for t in texts:
        for n in (1,2,3):
            freq.update(ngrams_from_text(t, n=n))
    proposals = []
    for p, count in freq.most_common(100)[:40]:
        proposals.append({
            "pattern": p,
            "label": f"ATOM_{p.upper().replace(' ', '_')[:64]}",
            "canonical_meaning": p,
            "compression_gain": 0.01 * count,
            "predictive_delta": 0.005 * count,
            "causal_utility": 0.1 + 0.01 * min(count, 50),
            "safety_risks": []
        })
    pool = await create_pool()
    async with pool.acquire() as conn:
        for p in proposals:
            await conn.execute("""
                INSERT INTO rebase_proposals (candidate_atoms, compression_gain, predictive_delta, causal_utility, safety_risks)
                VALUES ($1,$2,$3,$4,$5::jsonb)
            """, json.dumps([p]), p["compression_gain"], p["predictive_delta"], p["causal_utility"], json.dumps(p["safety_risks"]))
    return proposals

async def discover_candidates():
    # Check database size first; if small and lite_mode true, use fallback
    pool = await create_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT count(1) as cnt FROM interactions")
    cnt = int(row["cnt"]) if row else 0
    if settings.lite_mode and cnt < max(1000, settings.compaction_min_rows):
        return await discover_candidates_fallback()

    # when data large enough, run heavier pattern mining
    texts = await fetch_recent_texts(limit=20000)
    freq = Counter()
    for t in texts:
        for n in (1,2,3):
            freq.update(ngrams_from_text(t, n=n))
    proposals = []
    for p, count in freq.most_common(500)[:100]:
        proposals.append({
            "pattern": p,
            "label": f"ATOM_{p.upper().replace(' ', '_')[:64]}",
            "canonical_meaning": p,
            "compression_gain": min(0.5, 0.001*count),
            "predictive_delta": 0.01 * min(count, 100),
            "causal_utility": 0.2 + 0.01 * min(count, 100),
            "safety_risks": []
        })
    pool = await create_pool()
    async with pool.acquire() as conn:
        for p in proposals:
            await conn.execute("""
                INSERT INTO rebase_proposals (candidate_atoms, compression_gain, predictive_delta, causal_utility, safety_risks)
                VALUES ($1,$2,$3,$4,$5::jsonb)
            """, json.dumps([p]), p["compression_gain"], p["predictive_delta"], p["causal_utility"], json.dumps(p["safety_risks"]))
    return proposals

async def bee_loop():
    while True:
        try:
            await discover_candidates()
        except Exception as e:
            print("BEE error", e)
        await asyncio.sleep(600)

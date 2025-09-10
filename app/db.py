import asyncpg
import json
import hashlib
import datetime
from .settings import Settings

settings = Settings()
DSN = f"postgresql://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"

_pool = None

async def create_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
    return _pool

def compute_merkle(prev_hash: str, record: dict) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    combined = prev_hash.encode("utf-8") + payload
    return hashlib.sha256(combined).hexdigest()

async def get_latest_merkle(pool) -> str:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT merkle_root FROM interactions ORDER BY timestamp DESC LIMIT 1")
        if not row:
            return "0" * 64
        return row["merkle_root"]

async def insert_interaction(pool, input_text, output_text, input_emb, output_emb,
                             input_emb_c=None, output_emb_c=None, text_summary=None,
                             atom_refs=None, essence_refs=None, provider_response=None, metadata=None):
    prev = await get_latest_merkle(pool)
    record = {"input": input_text, "output": output_text, "timestamp": datetime.datetime.utcnow().isoformat()}
    merkle = compute_merkle(prev, record)
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO interactions (input_text, output_text, input_embedding, output_embedding,
                                      input_emb_compressed, output_emb_compressed, text_summary,
                                      atom_refs, essence_refs, merkle_root, provider_response, metadata)
            VALUES ($1,$2,$3::vector,$4::vector,$5::vector,$6::vector,$7,$8::jsonb,$9::jsonb,$10,$11::jsonb,$12::jsonb)
        """, input_text, output_text, input_emb, output_emb, input_emb_c, output_emb_c, text_summary,
             json.dumps(atom_refs or []), json.dumps(essence_refs or []), merkle, json.dumps(provider_response or {}), json.dumps(metadata or {}))
    return merkle

# Essence helpers: ensure an essence exists (based on signature), return essence_id
async def ensure_essence(pool, canonical_meaning: str, form: str = None, generation: str = None, meta: dict = None):
    """
    Ensure a canonical essence exists. Use signature (sha256 of canonical_meaning) to dedupe.
    If new, create essence row and add initial form_history entry.
    Returns essence_id (string UUID).
    """
    signature = hashlib.sha256(canonical_meaning.encode("utf-8")).hexdigest()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT essence_id FROM essences WHERE signature = $1", signature)
        if row:
            return str(row["essence_id"])
        # create new essence with initial form_history entry
        form_entry = []
        if form:
            entry = {"form": form, "generation": generation or "unknown", "added_at": datetime.datetime.utcnow().isoformat(), "meta": meta or {}}
            form_entry = [entry]
        await conn.execute("""
            INSERT INTO essences (canonical_meaning, signature, form_history)
            VALUES ($1, $2, $3::jsonb)
        """, canonical_meaning, signature, json.dumps(form_entry))
        row2 = await conn.fetchrow("SELECT essence_id FROM essences WHERE signature = $1", signature)
        return str(row2["essence_id"])

async def append_form_history(pool, essence_id: str, form: str, generation: str = None, meta: dict = None):
    async with pool.acquire() as conn:
        # fetch existing history
        row = await conn.fetchrow("SELECT form_history FROM essences WHERE essence_id = $1", essence_id)
        if not row:
            return False
        history = row["form_history"] or []
        entry = {"form": form, "generation": generation or "unknown", "added_at": datetime.datetime.utcnow().isoformat(), "meta": meta or {}}
        history.append(entry)
        await conn.execute("UPDATE essences SET form_history = $1::jsonb WHERE essence_id = $2", json.dumps(history), essence_id)
        return True

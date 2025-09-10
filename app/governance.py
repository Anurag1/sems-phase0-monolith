import asyncpg, hashlib, json
from .db import create_pool, ensure_essence, append_form_history
from .settings import Settings

settings = Settings()

async def verify_approver(api_key: str):
    if not api_key:
        return None
    pool = await create_pool()
    parts = api_key.split(":")
    if len(parts) != 2:
        return None
    username, secret = parts[0], parts[1]
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id, username, api_key_hash, role FROM governance_users WHERE username = $1", username)
        if not row:
            return None
        if hashlib.sha256(secret.encode()).hexdigest() == row["api_key_hash"]:
            return {"user_id": str(row["user_id"]), "username": row["username"], "role": row["role"]}
    return None

async def log_proposal_action(proposal_id: str, action: str, actor_user_id: str=None, actor_meta: dict=None):
    pool = await create_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO proposal_audit_log (proposal_id, action, actor_user_id, actor_meta)
            VALUES ($1,$2,$3,$4::jsonb)
        """, proposal_id, action, actor_user_id, json.dumps(actor_meta or {}))

import asyncio, hashlib
from .db import create_pool

async def seed():
    pool = await create_pool()
    username = "alice"
    secret = "supersecret123"
    api_key_hash = hashlib.sha256(secret.encode()).hexdigest()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO governance_users (username, api_key_hash, role) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", username, api_key_hash, "approver")
    print("seeded governance user alice with secret:", secret)

if __name__ == "__main__":
    asyncio.run(seed())

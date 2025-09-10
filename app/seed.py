import asyncio
from .db import create_pool, ensure_essence

async def seed_atomic_token():
    pool = await create_pool()
    # simple sample atom with canonical meaning
    canonical_meaning = "C-style for loop increment"
    form = "for (int i=0; i<n; i++)"
    async with pool.acquire() as conn:
        essence_id = await ensure_essence(pool, canonical_meaning, form=form, generation="G1")
        sample_emb = [0.001] * 1536
        sample_emb_comp = sample_emb[:256]
        await conn.execute("""
            INSERT INTO atomic_tokens (essence_id, label, base_repr, meaning, embedding, embedding_compressed, provenance, trust_score)
            VALUES ($1,$2,$3,$4,$5::vector,$6::vector,$7,$8)
            ON CONFLICT DO NOTHING
        """, essence_id, 'ATOM_LOOP_INC', form, canonical_meaning, sample_emb, sample_emb_comp, 'seed', 0.9)
    print("seeded atom with essence:", essence_id)

if __name__ == "__main__":
    asyncio.run(seed_atomic_token())

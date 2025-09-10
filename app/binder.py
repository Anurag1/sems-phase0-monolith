from typing import List, Dict
from .settings import Settings
import numpy as np

settings = Settings()

async def binder_lookup(conn, emb_compressed, top_k=3):
    """
    Find nearest atomic tokens by compressed embedding.
    Return token info including essence_id and form history reference.
    """
    rows = await conn.fetch(
        "SELECT token_id, essence_id, label, base_repr, meaning, trust_score FROM atomic_tokens "
        "ORDER BY embedding_compressed <-> $1::vector LIMIT $2",
        emb_compressed, top_k
    )
    results = []
    for r in rows:
        results.append({
            "token_id": str(r["token_id"]),
            "essence_id": str(r["essence_id"]) if r["essence_id"] else None,
            "label": r["label"],
            "base_repr": r["base_repr"],
            "meaning": r["meaning"],
            "score": float(r["trust_score"])
        })
    return results

def maybe_rewrite_prompt(prompt: str, binder_candidates: List[Dict]):
    """
    Rewrite using top candidate if confident. Also returns essence mapping in metadata.
    """
    if not binder_candidates:
        return prompt, {"rewritten": False, "essence": None}
    top = binder_candidates[0]
    if top["score"] >= settings.binder_score_threshold and top.get("base_repr") and top["base_repr"] in prompt:
        atom_marker = f"<ATOM:{top['label']}>"
        new_prompt = prompt.replace(top["base_repr"], atom_marker)
        return new_prompt, {"rewritten": True, "token_used": top, "essence": top.get("essence_id")}
    return prompt, {"rewritten": False, "essence": None}

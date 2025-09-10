from typing import List, Dict
from .settings import Settings
settings = Settings()
REWRITE_SCORE_THRESHOLD = settings.binder_score_threshold

def maybe_rewrite_prompt(prompt: str, binder_candidates: List[Dict]):
    if not binder_candidates:
        return prompt, {"rewritten": False, "essence": None}
    top = binder_candidates[0]
    if top.get("score", 0) >= REWRITE_SCORE_THRESHOLD and top.get("base_repr") and top["base_repr"] in prompt:
        atom_marker = f"<ATOM:{top['label']}>"
        new_prompt = prompt.replace(top["base_repr"], atom_marker)
        return new_prompt, {"rewritten": True, "token_used": top, "essence": top.get("essence_id")}
    return prompt, {"rewritten": False, "essence": None}

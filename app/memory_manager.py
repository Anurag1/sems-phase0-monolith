import os
import pickle
import asyncio
from typing import List
import numpy as np
from sklearn.decomposition import IncrementalPCA
import faiss
import hdbscan
from .db import create_pool
from .settings import Settings
import json

settings = Settings()
PCA_PATH = "/app/pca_model.pkl"
BATCH_SIZE = 256

def fit_pca_on_stream(embeddings_iter, compressed_dim=settings.compressed_dim):
    ipca = IncrementalPCA(n_components=compressed_dim, batch_size=BATCH_SIZE)
    for batch in embeddings_iter:
        ipca.partial_fit(np.array(batch, dtype=np.float32))
    with open(PCA_PATH, "wb") as f:
        pickle.dump(ipca, f)
    return ipca

def load_pca():
    if os.path.exists(PCA_PATH):
        with open(PCA_PATH, "rb") as f:
            return pickle.load(f)
    return None

def compress_embedding(emb: List[float]) -> List[float]:
    ipca = load_pca()
    arr = np.array(emb, dtype=np.float32).reshape(1, -1)
    if ipca:
        comp = ipca.transform(arr)[0].astype(np.float32)
        return comp.tolist()
    else:
        arr16 = arr.astype(np.float16)[0]
        target = settings.compressed_dim
        out = np.zeros((target,), dtype=np.float32)
        out[:min(len(arr16), target)] = arr16[:min(len(arr16), target)]
        return out.tolist()

async def estimate_interaction_count():
    pool = await create_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT count(1) as cnt FROM interactions")
    return int(row["cnt"]) if row else 0

async def fetch_compressed_embeddings(limit=20000):
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, input_emb_compressed, text_summary FROM interactions
            WHERE input_emb_compressed IS NOT NULL
            ORDER BY timestamp ASC
            LIMIT $1
        """, limit)
    ids, embs, sums = [], [], []
    for r in rows:
        emb = r['input_emb_compressed']
        if emb is None:
            continue
        ids.append(str(r['id']))
        embs.append(np.array(emb, dtype=np.float32))
        sums.append(r['text_summary'] or "")
    return ids, np.stack(embs) if embs else np.array([]), sums

def l2_normalize(X: np.ndarray):
    norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-12
    return X / norms

async def cluster_and_compact(min_cluster_size=8):
    # gate compaction in outer loop; here we assume called only when threshold exceeded
    ids, X, sums = await fetch_compressed_embeddings(limit=20000)
    if X.size == 0:
        return
    # subsample if large
    max_points = 20000
    if X.shape[0] > max_points:
        idxs = np.random.choice(X.shape[0], max_points, replace=False)
        X = X[idxs]
        ids = [ids[i] for i in idxs]
        sums = [sums[i] for i in idxs]

    X_norm = l2_normalize(X)
    # run HDBSCAN
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size, metric='euclidean', cluster_selection_method='eom')
    labels = clusterer.fit_predict(X_norm)
    clusters = {}
    for i, lbl in enumerate(labels):
        if lbl == -1:
            continue
        clusters.setdefault(lbl, []).append(i)

    pool = await create_pool()
    for lbl, idx_list in clusters.items():
        if len(idx_list) < min_cluster_size:
            continue
        chunk = X_norm[idx_list]
        centroid = np.mean(chunk, axis=0)
        refs = [ids[i] for i in idx_list]
        summary = " ".join(sums[i] for i in idx_list)[:2000]
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO centroids (label, centroid_emb, summary, refs)
                VALUES ($1, $2::vector, $3, $4::jsonb)
            """, f"cluster_{lbl}", centroid.tolist(), summary, json.dumps(refs))
            # delete originals to reclaim storage
            await conn.execute("DELETE FROM interactions WHERE id = ANY($1::uuid[])", refs)

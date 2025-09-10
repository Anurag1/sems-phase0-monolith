CREATE EXTENSION IF NOT EXISTS "pgvector";

-- essences table: the semantic DNA, persistent across generations
CREATE TABLE IF NOT EXISTS essences (
  essence_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_meaning TEXT,        -- human-readable canonical description
  signature TEXT UNIQUE,         -- e.g., sha256 of canonical_meaning (used to dedupe)
  form_history JSONB DEFAULT '[]'::jsonb,  -- list of {form, generation, added_at, meta}
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_essence_signature ON essences (signature);

-- interactions table (hot + compressed)
CREATE TABLE IF NOT EXISTS interactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  input_text TEXT,
  output_text TEXT,
  input_embedding vector(1536),
  output_embedding vector(1536),
  input_emb_compressed vector(256),
  output_emb_compressed vector(256),
  text_summary TEXT,
  atom_refs JSONB DEFAULT '[]'::jsonb,
  essence_refs JSONB DEFAULT '[]'::jsonb, -- list of essence_id(s) referenced by this interaction
  timestamp TIMESTAMPTZ DEFAULT NOW(),
  usage_score FLOAT DEFAULT 1.0,
  merkle_root TEXT NOT NULL,
  provider_response JSONB,
  metadata JSONB
);
CREATE INDEX IF NOT EXISTS idx_input_embedding ON interactions USING ivfflat (input_embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_input_emb_compressed ON interactions USING ivfflat (input_emb_compressed vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_timestamp ON interactions (timestamp);

-- atomic tokens (binder)
CREATE TABLE IF NOT EXISTS atomic_tokens (
  token_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  essence_id UUID REFERENCES essences(essence_id) ON DELETE SET NULL,
  label TEXT NOT NULL,
  base_repr TEXT,
  meaning TEXT,
  embedding vector(1536),
  embedding_compressed vector(256),
  provenance TEXT,
  version INT DEFAULT 1,
  trust_score FLOAT DEFAULT 0.5,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_atomic_embedding ON atomic_tokens USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_atomic_emb_comp ON atomic_tokens USING ivfflat (embedding_compressed vector_cosine_ops);

-- centroids (cold memory)
CREATE TABLE IF NOT EXISTS centroids (
  centroid_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  label TEXT,
  centroid_emb vector(256),
  summary TEXT,
  refs JSONB DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_centroid_emb ON centroids USING ivfflat (centroid_emb vector_cosine_ops);

-- rebase proposals (BEE)
CREATE TABLE IF NOT EXISTS rebase_proposals (
  proposal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_atoms JSONB,
  compression_gain FLOAT,
  predictive_delta FLOAT,
  causal_utility FLOAT,
  safety_risks JSONB,
  status TEXT DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- governance users & audit
CREATE TABLE IF NOT EXISTS governance_users (
  user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT UNIQUE NOT NULL,
  api_key_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS proposal_audit_log (
  log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  proposal_id UUID NOT NULL,
  action TEXT NOT NULL,
  actor_user_id UUID,
  actor_meta JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS governance_policies (
  policy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT UNIQUE NOT NULL,
  policy_json JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

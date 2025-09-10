from pydantic import BaseSettings

class Settings(BaseSettings):
    # network / app
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    api_key: str

    # postgres
    postgres_host: str
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str

    # LLM / embeddings provider (you can provide small & large models)
    embedding_url: str
    embedding_model: str = "text-embedding-3-small"
    llm_url: str
    llm_model_large: str = "gpt-4o-mini"     # high-quality, slower
    llm_model_small: str = "gpt-3o-fast"     # fast, cheaper (configure)
    provider_api_key: str

    # memory & compression
    hot_max_age_seconds: int = 600
    warm_max_age_seconds: int = 86400
    compressed_dim: int = 256
    binder_score_threshold: float = 0.80

    # performance/cost mitigation
    lite_mode: bool = True               # if True disables heavy compaction & reduces background freq
    compaction_min_rows: int = 1000      # only compact when interactions >= threshold
    compaction_check_interval: int = 600 # seconds (10min) default
    cache_ttl_seconds: int = 300         # cache TTL for LRU cache
    cache_max_items: int = 2048

    # local optional Redis
    use_redis_cache: bool = False
    redis_url: str = "redis://redis:6379/0"

    class Config:
        env_file = ".env"
        env_prefix = ""

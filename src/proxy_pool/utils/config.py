from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Scheduler intervals (minutes)
    fetch_interval: int = 30
    validate_interval: int = 5
    recheck_interval: int = 15

    # Scoring
    score_init: int = 10
    score_increment: int = 10
    score_decrement: int = 20
    score_max: int = 100

    # Validator
    validator_concurrency: int = 200
    validator_timeout: int = 10

    # Proxy cap per pool (0 = unlimited). cn and intl can be sized independently.
    cn_proxy_cap: int = 1000
    intl_proxy_cap: int = 1000

settings = Settings()

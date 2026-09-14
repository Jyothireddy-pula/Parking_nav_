from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ParkingNav-X API"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://parkingnavx:parkingnavx@localhost:5432/parkingnavx"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"
    # Where Module 9 trained model artifacts (model.joblib + evaluation.json
    # per campus/lot/horizon) are read from. Nothing here is ever written by
    # the API itself -- only training scripts (ml/prediction/train_external.py,
    # prediction/train_real.py) produce these files.
    prediction_model_dir: str = "../ml/artifacts/predictions"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PARKINGNAVX_", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_EXPIRES_MINUTES: int = 1440
    BOT_TOKEN: str
    ADMIN_INITIAL_PASSWORD: str = "change_me"

    class Config:
        env_file = ".env"

settings = Settings()

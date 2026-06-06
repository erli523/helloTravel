"""Application configuration placeholders."""

import os


class Settings:
    amap_api_key: str = os.getenv("AMAP_API_KEY", "")
    unsplash_api_key: str = os.getenv("UNSPLASH_API_KEY", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")


settings = Settings()

"""Application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    amap_api_key: str = Field(default="", alias="AMAP_API_KEY")
    amap_mcp_enabled: bool = Field(default=False, alias="AMAP_MCP_ENABLED")
    amap_mcp_name: str = Field(default="amap", alias="AMAP_MCP_NAME")
    amap_mcp_runner: Literal["npx", "uvx"] = Field(
        default="npx", alias="AMAP_MCP_RUNNER"
    )
    amap_mcp_package: str = Field(
        default="@sugarforever/amap-mcp-server",
        alias="AMAP_MCP_PACKAGE",
    )

    unsplash_api_key: str = Field(default="", alias="UNSPLASH_ACCESS_KEY")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")

    @property
    def amap_mcp_command(self) -> list[str]:
        if self.amap_mcp_runner == "uvx":
            return ["uvx", self.amap_mcp_package]
        return ["npx", "-y", self.amap_mcp_package]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

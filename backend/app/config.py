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
        default="@amap/amap-maps-mcp-server",
        alias="AMAP_MCP_PACKAGE",
    )
    amap_mcp_tool_timeout: float = Field(default=15.0, alias="AMAP_MCP_TOOL_TIMEOUT")
    amap_rest_preferred: bool = Field(default=True, alias="AMAP_REST_PREFERRED")

    unsplash_api_key: str = Field(default="", alias="UNSPLASH_ACCESS_KEY")
    unsplash_enabled: bool = Field(default=True, alias="UNSPLASH_ENABLED")
    unsplash_base_url: str = Field(
        default="https://api.unsplash.com", alias="UNSPLASH_BASE_URL"
    )
    unsplash_timeout: float = Field(default=10.0, alias="UNSPLASH_TIMEOUT")
    unsplash_per_page: int = Field(default=1, alias="UNSPLASH_PER_PAGE")
    image_enrich_timeout: float = Field(default=12.0, alias="IMAGE_ENRICH_TIMEOUT")

    llm_model_id: str = Field(default="deepseek-v4-flash", alias="LLM_MODEL_ID")
    llm_enabled: bool = Field(default=True, alias="LLM_ENABLED")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_base_url: str = Field(default="https://api.deepseek.com/v1", alias="LLM_BASE_URL")
    llm_timeout: float = Field(default=60.0, alias="LLM_TIMEOUT")
    agent_response_timeout: float = Field(default=20.0, alias="AGENT_RESPONSE_TIMEOUT")
    planning_timeout: float = Field(default=150.0, alias="PLANNING_TIMEOUT")
    react_debug_enabled: bool = Field(default=True, alias="REACT_DEBUG_ENABLED")

    dashscope_api_key: str = Field(default="", alias="DASHSCOPE_API_KEY")
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="DASHSCOPE_BASE_URL",
    )

    qdrant_url: str = Field(default="", alias="QDRANT_URL")
    qdrant_api_key: str = Field(default="", alias="QDRANT_API_KEY")

    neo4j_uri: str = Field(default="", alias="NEO4J_URI")
    neo4j_username: str = Field(default="", alias="NEO4J_USERNAME")
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD")
    neo4j_database: str = Field(default="neo4j", alias="NEO4J_DATABASE")
    aura_instance_id: str = Field(default="", alias="AURA_INSTANCEID")
    aura_instance_name: str = Field(default="", alias="AURA_INSTANCENAME")

    @property
    def amap_mcp_command(self) -> list[str]:
        if self.amap_mcp_runner == "uvx":
            return ["uvx", self.amap_mcp_package]
        return ["npx", "-y", self.amap_mcp_package]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

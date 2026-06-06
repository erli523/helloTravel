"""Shared Agent abstractions."""

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field


T = TypeVar("T")


class AgentTrace(BaseModel):
    """Observable metadata for one Agent step."""

    agent_name: str = Field(..., description="Agent name")
    prompt: str = Field(..., description="Role prompt")
    user_query: str = Field(..., description="Query sent to the Agent")
    tool_calls: list[str] = Field(default_factory=list, description="Tool calls")
    summary: str = Field(..., description="Short response summary")


@dataclass(frozen=True)
class AgentResult(Generic[T]):
    """Structured Agent output plus trace data."""

    data: T
    trace: AgentTrace


class BaseAgent:
    """Base class for role-specific Agents."""

    name: str = "base_agent"
    prompt_template: str = ""

    def __init__(self, amap_tools: Any | None = None) -> None:
        self.amap_tools = amap_tools

    def render_prompt(self, **kwargs: object) -> str:
        return self.prompt_template.format(**kwargs)

    def toolset_summary(self) -> str:
        if self.amap_tools is None:
            return "No shared MCP toolset attached."
        return self.amap_tools.describe()

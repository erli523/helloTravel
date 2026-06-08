"""Shared planning context for multi-agent collaboration."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


StepKind = Literal["observation", "thought", "action", "result", "repair"]


class ContextStep(BaseModel):
    """One observable ReAct-style step produced during planning."""

    agent_name: str
    kind: StepKind
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AgentDecision(BaseModel):
    """Structured decision made by a specialist or planner agent."""

    agent_name: str
    decision_type: str
    summary: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)


class PlanningContextBus:
    """Request-scoped context bus shared by all agents."""

    def __init__(self) -> None:
        self.steps: list[ContextStep] = []
        self.decisions: list[AgentDecision] = []
        self.artifacts: dict[str, Any] = {}

    def observe(self, agent_name: str, message: str, **data: Any) -> None:
        self.steps.append(
            ContextStep(agent_name=agent_name, kind="observation", message=message, data=data)
        )

    def think(self, agent_name: str, message: str, **data: Any) -> None:
        self.steps.append(
            ContextStep(agent_name=agent_name, kind="thought", message=message, data=data)
        )

    def act(self, agent_name: str, message: str, **data: Any) -> None:
        self.steps.append(
            ContextStep(agent_name=agent_name, kind="action", message=message, data=data)
        )

    def result(self, agent_name: str, message: str, **data: Any) -> None:
        self.steps.append(
            ContextStep(agent_name=agent_name, kind="result", message=message, data=data)
        )

    def repair(self, agent_name: str, message: str, **data: Any) -> None:
        self.steps.append(
            ContextStep(agent_name=agent_name, kind="repair", message=message, data=data)
        )

    def decide(
        self,
        *,
        agent_name: str,
        decision_type: str,
        summary: str,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> None:
        self.decisions.append(
            AgentDecision(
                agent_name=agent_name,
                decision_type=decision_type,
                summary=summary,
                inputs=inputs or {},
                outputs=outputs or {},
            )
        )

    def put_artifact(self, key: str, value: Any) -> None:
        self.artifacts[key] = value

    def snapshot(self) -> dict[str, Any]:
        return {
            "steps": [step.model_dump() for step in self.steps],
            "decisions": [decision.model_dump() for decision in self.decisions],
            "artifacts": self.artifacts,
        }

    def trace_summary_for(self, agent_name: str) -> dict[str, Any]:
        return {
            "steps": [
                step.model_dump()
                for step in self.steps
                if step.agent_name == agent_name
            ],
            "decisions": [
                decision.model_dump()
                for decision in self.decisions
                if decision.agent_name == agent_name
            ],
        }

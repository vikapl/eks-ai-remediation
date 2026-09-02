"""
models.py

Plain dataclasses shared by every module. Keeping these in one place (rather
than each module inventing its own dict shape) is what lets handler.py stay
analyzer-agnostic: MockAnalyzer and BedrockAnalyzer both hand back the exact
same Diagnosis shape, so handler.py never needs an if/else on which provider
produced it - that's the whole point of the swappable-analyzer design.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Incident:
    """Everything the analyzer/remediator need, extracted from the raw
    EventBridge event so the rest of the code never touches raw event JSON."""

    alarm_name: str
    alarm_description: str
    cluster_name: str
    namespace: Optional[str]
    deployment: Optional[str]
    nodegroup: Optional[str]
    metric_name: Optional[str]
    region: str
    account_id: str
    raw_event: dict = field(default_factory=dict)


@dataclass
class Diagnosis:
    """The analyzer's output. `remediation_type` is a controlled vocabulary
    (restart_deployment / scale_nodegroup / manual_investigation) because
    handler.py uses it to decide whether to act - a free-text field here
    would make the policy gate in handler.py impossible to enforce safely."""

    root_cause: str
    explanation: str
    confidence: float  # 0.0-1.0
    remediation_type: str
    suggested_command: str
    provider: str  # "mock" | "bedrock" - which analyzer produced this

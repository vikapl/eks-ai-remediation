"""
analyzer/bedrock_analyzer.py

The real LLM path - a live call to Claude on Amazon Bedrock. This is
written, correct, and ready to deploy, but not what's running right now
(AI_PROVIDER=mock is the default): using it means enabling Bedrock model
access in the account and accepting a small per-invocation cost, and I'd
rather demo the whole pipeline for free first and flip this on deliberately.

It implements the exact same IncidentAnalyzer interface as MockAnalyzer, so
switching providers is a one-variable Terraform change (var.ai_provider),
not a code change.
"""
import json

import boto3

from analyzer.base import IncidentAnalyzer
from models import Diagnosis, Incident

# I ask the model for structured JSON output rather than free text, using
# the same controlled vocabulary for remediation_type that the mock
# analyzer and handler.py's policy gate expect. An LLM that's allowed to
# invent its own remediation_type values would break the allow-list
# safety check in handler.py - the *format* of the answer is part of the
# safety design here, not just its content.
_SYSTEM_PROMPT = """You are an SRE assistant diagnosing a single Kubernetes/EKS \
incident from a CloudWatch alarm. Respond with ONLY a JSON object (no prose, \
no markdown fences) with exactly these keys:

- root_cause: one sentence, the most likely cause
- explanation: 2-4 sentences, plain English, aimed at an engineer who will \
act on this
- confidence: a float between 0 and 1
- remediation_type: one of exactly "restart_deployment", "scale_nodegroup", \
or "manual_investigation" - never invent a new value
- suggested_command: a single shell command (kubectl or aws cli) the \
engineer could run to confirm or act on this

If you are not confident, say so honestly with a low confidence score and \
remediation_type "manual_investigation" rather than guessing."""


class BedrockAnalyzer(IncidentAnalyzer):
    def __init__(self, model_id: str, region: str):
        self._model_id = model_id
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def analyze(self, incident: Incident) -> Diagnosis:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": self._build_prompt(incident)}],
        }

        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())
        parsed = json.loads(payload["content"][0]["text"])

        return Diagnosis(
            root_cause=parsed["root_cause"],
            explanation=parsed["explanation"],
            confidence=float(parsed["confidence"]),
            remediation_type=parsed["remediation_type"],
            suggested_command=parsed["suggested_command"],
            provider="bedrock",
        )

    @staticmethod
    def _build_prompt(incident: Incident) -> str:
        return (
            f"CloudWatch alarm '{incident.alarm_name}' entered ALARM state.\n"
            f"Alarm description: {incident.alarm_description or '(none)'}\n"
            f"Cluster: {incident.cluster_name}\n"
            f"Namespace: {incident.namespace or 'unknown'}\n"
            f"Deployment: {incident.deployment or 'unknown'}\n"
            f"Nodegroup: {incident.nodegroup or 'n/a'}\n"
            f"Metric: {incident.metric_name or 'unknown'}\n"
        )

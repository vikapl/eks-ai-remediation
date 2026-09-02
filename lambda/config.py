"""
config.py

Reads every runtime knob from environment variables - all set by Terraform's
`environment { variables = {...} }` block (see terraform/lambda.tf), so this
file and that block have to agree on names. Defaults here are what a purely
local run (tests/local_test.py) gets if it doesn't set anything: mock
analyzer, auto-remediate off. That's deliberate - the safe path should also
be the path of least resistance.
"""
import os
from dataclasses import dataclass
from typing import Set


@dataclass
class Config:
    ai_provider: str
    bedrock_model_id: str
    auto_remediate: bool
    allowed_auto_actions: Set[str]
    eks_cluster_name: str
    slack_secret_arn: str
    max_nodegroup_scale_step: int
    aws_region: str


def load_config() -> Config:
    """Reads fresh from the environment every call, rather than caching a
    module-level singleton at import time. That's what lets
    tests/local_test.py flip env vars between fixtures and get a genuinely
    different Config each time, instead of fighting Python's import cache."""
    return Config(
        ai_provider=os.environ.get("AI_PROVIDER", "mock"),
        bedrock_model_id=os.environ.get(
            "BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0"
        ),
        auto_remediate=os.environ.get("AUTO_REMEDIATE", "false").strip().lower() == "true",
        allowed_auto_actions={
            a.strip()
            for a in os.environ.get("ALLOWED_AUTO_ACTIONS", "restart_deployment").split(",")
            if a.strip()
        },
        eks_cluster_name=os.environ.get("EKS_CLUSTER_NAME", ""),
        slack_secret_arn=os.environ.get("SLACK_SECRET_ARN", ""),
        max_nodegroup_scale_step=int(os.environ.get("MAX_NODEGROUP_SCALE_STEP", "1")),
        aws_region=os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")),
    )

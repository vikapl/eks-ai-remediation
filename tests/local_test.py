#!/usr/bin/env python3
"""
tests/local_test.py

Runs the real Lambda handler against sample EventBridge events, entirely
offline. AI_PROVIDER=mock avoids any LLM call, SLACK_SECRET_ARN is left
unset so notify_slack.py prints instead of posting, and AUTO_REMEDIATE
defaults to false so no AWS/Kubernetes API call happens either. This is the
exact same handler.lambda_handler() function AWS would invoke in prod -
there's no separate "test version" of the logic anywhere in this project.

Usage:
    python3 -m venv .venv && ./.venv/bin/pip install -r lambda/requirements.txt
    ./.venv/bin/python tests/local_test.py
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
LAMBDA_DIR = ROOT / "lambda"
FIXTURES_DIR = ROOT / "tests" / "fixtures"

# The Lambda's source layout puts handler.py at the zip root and imports
# sibling modules (models, config, analyzer, ...) directly - so running it
# locally without touching a single import in the real source means putting
# lambda/ on sys.path, exactly like AWS does at cold start.
sys.path.insert(0, str(LAMBDA_DIR))

# Safe, fully-offline defaults - nothing below talks to AWS.
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("AUTO_REMEDIATE", "false")
os.environ.setdefault("ALLOWED_AUTO_ACTIONS", "restart_deployment")
os.environ.setdefault("EKS_CLUSTER_NAME", "redhat-25c-dev")
os.environ.setdefault("AWS_REGION", "us-east-1")
# SLACK_SECRET_ARN intentionally left unset -> notify_slack.py prints instead of POSTing.

FIXTURES = [
    "alarm_event_crashloop.json",
    "alarm_event_node_notready.json",
    "alarm_event_high_cpu.json",
]


def _load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


def run_recommend_only():
    import handler

    print("\n" + "=" * 72)
    print("PASS 1 - recommend-only mode (AUTO_REMEDIATE=false, the actual default)")
    print("=" * 72)

    for name in FIXTURES:
        event = _load_fixture(name)
        print(f"\n--- {name} ---")
        result = handler.lambda_handler(event, None)
        print(json.dumps(result, indent=2))


def run_auto_remediate_demo():
    """Same CrashLoopBackOff incident, but with AUTO_REMEDIATE=true and
    restart_deployment allow-listed, to show the policy gate actually
    letting an action through. The Kubernetes call itself is mocked - this
    sandbox has no real EKS cluster to reach - so what this demonstrates is
    the DECISION LOGIC in handler.py (would it act, and on what), not a
    live cluster mutation. Deploying the Terraform for real is what proves
    eks_client.py's IRSA-based auth actually works end to end."""
    import handler

    print("\n" + "=" * 72)
    print("PASS 2 - auto-remediate demo (AUTO_REMEDIATE=true), K8s call mocked")
    print("=" * 72)

    os.environ["AUTO_REMEDIATE"] = "true"
    fake_result = {
        "status": "executed",
        "action": "restart_deployment",
        "detail": "Restarted rollout for deployment/payments-api in namespace/payments",
    }

    with patch("remediate.restart_deployment", return_value=fake_result) as mocked:
        event = _load_fixture("alarm_event_crashloop.json")
        result = handler.lambda_handler(event, None)
        print(json.dumps(result, indent=2))
        assert mocked.called, "expected restart_deployment to be invoked once the gate passed"

    os.environ["AUTO_REMEDIATE"] = "false"


if __name__ == "__main__":
    run_recommend_only()
    run_auto_remediate_demo()
    print("\nAll fixtures ran without errors.\n")

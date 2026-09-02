#!/usr/bin/env python3
"""
tests/test_analyzer.py

Direct checks on MockAnalyzer's pattern matching - the part of this project
I'd most want a regression test on, since it's hand-written domain knowledge
(analyzer/mock_analyzer.py) rather than boilerplate. Runnable with plain
`python3 tests/test_analyzer.py` - no pytest dependency needed for a project
this size.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambda"))

from analyzer.mock_analyzer import MockAnalyzer
from models import Incident


def _incident(alarm_name, **overrides):
    base = dict(
        alarm_name=alarm_name,
        alarm_description="",
        cluster_name="redhat-25c-dev",
        namespace="payments",
        deployment="payments-api",
        nodegroup=None,
        metric_name=None,
        region="us-east-1",
        account_id="340924313311",
    )
    base.update(overrides)
    return Incident(**base)


def test_crashloop_maps_to_restart():
    diagnosis = MockAnalyzer().analyze(_incident("eks-crashloop-backoff-payments-api"))
    assert diagnosis.remediation_type == "restart_deployment"
    assert diagnosis.confidence > 0
    assert "payments-api" in diagnosis.suggested_command


def test_node_notready_maps_to_scale():
    diagnosis = MockAnalyzer().analyze(
        _incident("eks-node-notready-general", namespace=None, deployment=None, nodegroup="general")
    )
    assert diagnosis.remediation_type == "scale_nodegroup"
    assert "general" in diagnosis.suggested_command


def test_oom_never_auto_acts():
    diagnosis = MockAnalyzer().analyze(_incident("eks-oomkilled-checkout-worker"))
    assert diagnosis.remediation_type == "manual_investigation"


def test_unknown_pattern_falls_back_honestly():
    diagnosis = MockAnalyzer().analyze(_incident("eks-something-nobody-has-seen-before"))
    assert diagnosis.confidence == 0.0
    assert diagnosis.remediation_type == "manual_investigation"


if __name__ == "__main__":
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed")

# eks-ai-remediation

An AI-assisted AWS remediation workflow: CloudWatch alarms I already built
for EKS (Story 2.3 on the capstone) fire into EventBridge, which triggers a
Lambda that diagnoses the incident, posts a recommendation to Slack, and -
only for a short, explicitly allow-listed set of incident types - can take
the fix itself.

This is the real, working, small-scale version of that project. It runs
fully offline for now (`tests/local_test.py` exercises the actual Lambda
handler with zero AWS calls); the Terraform is written to be deployed for
real into my capstone AWS account (340924313311, us-east-1) whenever I'm
ready to wire it up against a live cluster.

## Why this exists

Story 2.3 gave the team eyes on EKS problems - alarms, Prometheus rules,
Alertmanager routing to Slack, runbooks. What it didn't give us was a first
response faster than "a human reads the Slack message and runs a command."
For the handful of incident types that have an unambiguous, safe fix
(a CrashLoopBackOff pod that just needs a rollout restart, a NotReady node
that needs one more node to pick up the slack), that gap is pure toil. This
project closes it for exactly those cases, and stays deliberately
conservative everywhere else.

## Architecture

```
CloudWatch Alarm (Story 2.3)
        |  state -> ALARM
        v
EventBridge rule (eks-* alarms only)
        |
        v
Lambda: eks-ai-remediation
   1. parse the event into an Incident
   2. analyzer.analyze(incident) -> Diagnosis        <-- the "AI" step
   3. policy gate: auto_remediate? allow-listed?
        no  -> recommend only
        yes -> remediate.restart_deployment() / scale_nodegroup()
   4. always: post the diagnosis + outcome to Slack
```

The analyzer is swappable behind one interface (`analyzer/base.py`):
`mock_analyzer.py` is a small rule-based knowledge base (free, deterministic,
what's running today); `bedrock_analyzer.py` is a real Claude-on-Bedrock
call, written and ready, not yet turned on (`var.ai_provider`).

See `docs/ARCHITECTURE.md` for the full design rationale - why
EventBridge's native "CloudWatch Alarm State Change" event instead of a
custom publisher, why EKS access entries instead of the aws-auth ConfigMap,
why the policy gate lives in the handler and not in each remediation
function.

## Project layout

```
terraform/            IaC: EventBridge rule, Lambda, IAM, EKS access entry + RBAC
  versions.tf            provider requirements + kubernetes provider auth
  variables.tf            every configurable knob (no hardcoded values)
  iam.tf                  least-privilege Lambda execution role
  eks_access.tf           EKS access entry + scoped Kubernetes Role/RoleBinding
  lambda.tf               the function, log group, DLQ, packaging
  eventbridge.tf          the trigger rule + target
  outputs.tf

lambda/                The function's actual source (this is what gets zipped)
  handler.py              entry point + policy gate
  config.py               env var -> Config
  models.py               Incident / Diagnosis dataclasses
  analyzer/
    base.py                 the IncidentAnalyzer interface
    mock_analyzer.py         rule-based analyzer (default, free)
    bedrock_analyzer.py      real Claude-on-Bedrock analyzer (opt-in)
  eks_client.py            IRSA-style STS -> Kubernetes bearer token
  remediate.py             the two automatable actions
  notify_slack.py          Slack delivery (Secrets Manager, Story 2.3 pattern)

tests/
  fixtures/                3 realistic CloudWatch Alarm State Change events
  local_test.py            runs the real handler against all 3, fully offline
  test_analyzer.py         unit tests on the mock analyzer's pattern matching

docs/
  ARCHITECTURE.md          design rationale, diagrams, trade-offs
  RUNBOOK.md               what to do when this fires / how to extend it safely
  INTERVIEW-NOTES.md       my own notes for talking about this end to end
```

## Running it locally (no AWS needed)

```bash
python3 -m venv .venv
./.venv/bin/pip install -r lambda/requirements.txt

./.venv/bin/python tests/test_analyzer.py   # unit tests on the mock analyzer
./.venv/bin/python tests/local_test.py      # runs the real handler end to end
```

`local_test.py` runs two passes: recommend-only (the actual default) against
all three sample incidents, then a second pass with `AUTO_REMEDIATE=true`
showing the policy gate actually approving an action (the Kubernetes call
itself is mocked, since there's no real cluster reachable from a laptop
without a kubeconfig/VPN to it).

## Deploying for real

Not done yet, deliberately (see the "Deploy scope" decision below) - but
the path is:

```bash
cd terraform
terraform init
terraform plan \
  -var="eks_cluster_name=redhat-25c-dev" \
  -var="slack_webhook_secret_arn=<arn from Story 2.3>"
terraform apply ...
```

`terraform apply` needs credentials that can reach the EKS cluster's API
(for the `kubernetes` provider's data sources) in addition to normal AWS
permissions - same requirement Terraform already has for any module that
manages Kubernetes objects.

Start with `auto_remediate = false` (the default) and watch the Slack
recommendations for a while before flipping it on for
`restart_deployment` only.

## Safety model, in one paragraph

Two independent gates have to pass before this system touches anything:
`auto_remediate` (an account-wide off switch, off by default) and
`allowed_auto_actions` (a per-incident-type allow-list - `manual_investigation`
is never on it, by design). Even when both pass, the only two actions
available are a rollout restart (can't change what's deployed, only ask
Kubernetes to retry it) and a one-node nodegroup bump capped at the
nodegroup's own `maxSize`. Every decision - act or don't, and why - is
logged as structured JSON and posted to Slack either way.

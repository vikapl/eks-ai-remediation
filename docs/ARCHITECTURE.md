# Architecture

## The trigger: why CloudWatch Alarm State Change, not a custom publisher

EventBridge's default event bus already receives a `CloudWatch Alarm State
Change` event every time *any* alarm in the account changes state - I don't
have to write anything to make my Story 2.3 alarms "send" events anywhere.
The EventBridge rule is purely a filter on events that already exist:

```json
{
  "source": ["aws.cloudwatch"],
  "detail-type": ["CloudWatch Alarm State Change"],
  "detail": {
    "alarmName": [{ "prefix": "eks-" }],
    "state": { "value": ["ALARM"] }
  }
}
```

The `eks-` prefix match is a deliberate second layer of narrowing on top of
whatever filtering happens inside the Lambda - the rule itself should never
even see, say, a billing alarm. Two independent places narrowing scope beats
one, the same principle behind the IAM + Kubernetes RBAC split below.

## Why the analyzer is a swappable interface, not a single script

`analyzer/base.py` defines one method: `analyze(incident) -> Diagnosis`.
`handler.py` only ever calls that method through `analyzer/__init__.py`'s
`get_analyzer(provider)` factory - it never imports `MockAnalyzer` or
`BedrockAnalyzer` directly. That's what makes `AI_PROVIDER=mock` vs.
`AI_PROVIDER=bedrock` a one-variable Terraform change instead of a rewrite:
every other module (the policy gate, remediation, Slack formatting) is
written against the `Diagnosis` shape, never against which provider produced
it.

I started with the mock analyzer, not because a real LLM call is hard to
wire up, but because writing the mock's knowledge base *is* the design work
- I had to write down, in plain English, what I actually believe causes a
CrashLoopBackOff vs. an OOMKill vs. a NotReady node, and what I trust an
automated system to do about each one. `bedrock_analyzer.py`'s system prompt
is built from that same mental model; the mock isn't a placeholder I'll
throw away, it's the spec the real model has to match.

## Why EKS access entries instead of the aws-auth ConfigMap

The traditional way to give an IAM role access to an EKS cluster is editing
the `aws-auth` ConfigMap in `kube-system` - a YAML edit that isn't a real
AWS resource, so Terraform managing it means either fighting anyone else who
edits that ConfigMap by hand, or a fragile `kubectl_manifest` workaround.

EKS access entries (`aws_eks_access_entry` in `eks_access.tf`) are a
first-class AWS API - the grant shows up in `terraform plan` like any other
resource, and it's visible via `aws eks list-access-entries` without anyone
needing `kubectl` access to the cluster at all.

I used `type = "STANDARD"` with **no** AWS-managed access policy attached.
AWS's managed EKS access policies (`AmazonEKSAdminPolicy`,
`AmazonEKSEditPolicy`, etc.) are all cluster-wide or namespace-wide at
best - there's no managed policy that means "only patch Deployments, only in
these two namespaces." So the access entry does exactly one thing: it lets
the Lambda's IAM role authenticate to the cluster and be recognized as
Kubernetes group `eks-ai-remediation-bot`. What that group can *do* is
defined entirely by the native `kubernetes_role` / `kubernetes_role_binding`
resources next to it - `get/list/patch` on `deployments`, `get/list` on
`pods`, in the `default` and `payments` namespaces only. IAM gets the bot in
the door; Kubernetes RBAC decides what it can touch once inside. Two
independent systems, both have to agree.

## Why the Kubernetes auth is a hand-rolled STS token, not the AWS CLI

`eks_client.py` reproduces what `aws eks get-token` / aws-iam-authenticator
do: sign an STS `GetCallerIdentity` request with an `x-k8s-aws-id: <cluster>`
header, presign it, and base64-encode it into a `k8s-aws-v1.` bearer token.
EKS's built-in webhook token authenticator verifies that token against IAM
without me running any separate authenticator service.

I didn't shell out to the AWS CLI to do this, because the CLI isn't
guaranteed to be present (or the same version) in the Lambda Python runtime.
Doing it with `boto3` + `botocore.signers.RequestSigner` keeps the entire
auth path inside the two dependencies already in `requirements.txt`.

## Why the policy gate lives in `handler.py`, not in `remediate.py`

`remediate.py`'s functions have no idea whether they're allowed to run -
they just run, safely, when called. "Is it safe to act on *this* incident,
right now, given the current config" is a decision that depends on the
incident (its `remediation_type`) and on runtime config
(`auto_remediate`, `allowed_auto_actions`) - not a property of the action
itself. Putting that decision in `handler.py`'s `_maybe_remediate()` means
there's exactly one place in the whole codebase that decides whether
anything happens automatically, which is also the one place I'd point a
reviewer (or an interviewer) to when they ask "how do I know this can't run
away from you."

## Failure handling

- **DLQ (`aws_sqs_queue.remediation_dlq`)**: if the Lambda throws after
  exhausting retries, the triggering event lands here instead of vanishing.
  An alarm on this queue's depth is the natural next addition - "the
  auto-remediator is failing" deserves its own page, same as any other gap
  I'd flag reviewing Story 2.3's alerting coverage.
- **EventBridge target retry policy**: separate from the DLQ - two retries
  over 10 minutes if EventBridge itself can't deliver to the Lambda (throttling,
  transient errors), before the event is considered failed at the
  EventBridge layer.
- **Structured logging**: every diagnosis is logged as one JSON line
  (`handler.py`'s `logger.info(json.dumps(...))`) - alarm name, cluster,
  namespace, deployment, root cause, confidence, remediation type, which
  analyzer produced it. That's the audit trail for "why did the bot restart
  payments-api at 2am."

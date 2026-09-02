# Runbook

## What happens when an eks-* alarm fires

1. EventBridge matches the alarm state change and invokes
   `eks-ai-remediation-<env>`.
2. The Lambda logs a structured `diagnosis_complete` line to
   `/aws/lambda/eks-ai-remediation-<env>` - alarm name, cluster, namespace,
   deployment, root cause, confidence, remediation type, analyzer provider.
3. A message is posted to the same Slack channel Story 2.3's alarms already
   go to: the diagnosis, the suggested command, and what automation did (or
   didn't) do.
4. If the incident's `remediation_type` was both allow-listed **and**
   `auto_remediate` is on, the action already happened by the time the Slack
   message posts - the message says `executed`, not `will execute`.

## If the DLQ has messages

`aws_sqs_queue.remediation_dlq` fills when the Lambda throws after
exhausting EventBridge's retries. Check:

```bash
aws sqs receive-message --queue-url <dead_letter_queue_url output> --max-number-of-messages 5
```

Each message is the original EventBridge event that failed - replay it
locally with `tests/local_test.py`'s pattern (load it as a fixture, call
`handler.lambda_handler`) to reproduce the failure before touching
production config.

## Turning on auto-remediation for real

Don't flip `auto_remediate = true` the same day this is first deployed.
Sequence:

1. Deploy with `auto_remediate = false` (the default). Let it run in
   recommend-only mode against real alarms for at least a few incidents -
   confirm the diagnoses it's producing actually match what I'd have
   concluded by hand.
2. Set `auto_remediate = true` with `allowed_auto_actions = ["restart_deployment"]`
   only - the lower-risk of the two actions (it can't change what's
   running, only ask Kubernetes to retry the current revision).
3. Only after that's been stable, consider adding `"scale_nodegroup"` to
   the allow-list.

## Extending the allow-list or the incident knowledge base

- New automatable action: add a function to `remediate.py`, add its
  `remediation_type` string to a mock (or Bedrock prompt) response, wire a
  branch in `handler._maybe_remediate()`, and add it to
  `var.allowed_auto_actions` in Terraform - deliberately four separate
  places, so adding automation is never a one-line change nobody notices in
  review.
- New incident pattern for the mock analyzer: add an entry to
  `_KNOWLEDGE_BASE` in `analyzer/mock_analyzer.py` and a regression test in
  `tests/test_analyzer.py`.

## Rolling back

`auto_remediate = false` (or removing an action from `allowed_auto_actions`)
is the fast rollback - it's a Terraform var change, applies in under a
minute, and immediately puts every future incident of that type back to
recommend-only. Disabling the EventBridge rule entirely
(`aws_cloudwatch_event_rule.eks_alarm_state_change` - toggle via the console
or `enabled = false` in Terraform) stops the whole pipeline, including
diagnosis and Slack notification, if something about the analysis itself
looks wrong.

## Known limitations (things I'd flag before anyone assumes this is
production-hardened)

- Deployment name is *inferred* from the pod name dimension
  (`payments-api-7f8d9c9c6b-4xkpq` -> `payments-api`) because Container
  Insights doesn't expose a `Deployment` dimension directly. StatefulSets or
  unusually-named pods can break this; when it can't confidently determine
  a namespace/deployment, `handler._maybe_remediate()` skips automated
  action rather than guessing.
- The mock analyzer only recognizes five incident patterns. Anything else
  gets an honest "I don't know" (`confidence: 0.0`, `manual_investigation`)
  - it will never fabricate a diagnosis for something it hasn't seen.
- `scale_nodegroup` adds capacity but never scales back down - a
  complementary scale-in policy (or just leaving that to Cluster Autoscaler,
  which should already be running) is the honest answer to "does this leave
  extra nodes running forever," and worth saying out loud rather than
  implying this is a complete capacity story.

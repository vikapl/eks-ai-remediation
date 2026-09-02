# My notes for talking about this project

Not a script - just what I want to have straight in my head before I'm
asked about the "AI-assisted AWS remediation" line, so I'm explaining
something I built and tested, not reciting a bullet point.

## The 30-second version

"I extended the CloudWatch/Alertmanager alerting I built for our EKS
cluster with an automated first-response layer: EventBridge picks up
CloudWatch alarms going into ALARM state, invokes a Lambda that diagnoses
the incident and posts a recommendation to Slack, and - only for a couple
of incident types I explicitly allow-listed, like CrashLoopBackOff - can
restart the deployment itself. Everything else stays recommend-only."

That's the whole shape. Everything below is depth for when they push on a
piece of it.

## If they ask "what does the AI actually do"

Be precise, don't oversell it: right now it's a rule-based analyzer
(pattern-matches the alarm against five known incident types and returns a
root cause + suggested fix), built behind the same interface a real LLM
call uses. I wrote `bedrock_analyzer.py` - a real, working Claude-on-Bedrock
call - but haven't turned it on, because I wanted to prove the pipeline and
the safety gates for free before paying for and depending on live model
calls. That's a legitimate engineering sequencing decision, not a shortcut -
I'd say so plainly if asked why it's not live.

## If they ask "how do you keep it from doing something dangerous"

Two independent gates, both have to pass: an account-wide
`auto_remediate` flag (off by default) and a per-incident-type allow-list.
Even when both pass, the only two actions that exist are a rollout restart
(can't change what's deployed, only retries the current revision) and a
one-node nodegroup bump capped at the nodegroup's configured max. I also
split IAM from Kubernetes RBAC on purpose - the Lambda's IAM role only gets
it in the door to the cluster (via an EKS access entry), and a scoped
Kubernetes Role decides it can only patch Deployments in two namespaces.
Two permission systems, both have to agree.

## If they ask "how did you test this without a real cluster"

`tests/local_test.py` runs the actual `handler.lambda_handler()` - the same
function AWS invokes - against three realistic sample events, entirely
offline: mock analyzer (no API calls), no Slack webhook configured (prints
instead of posting), and `AUTO_REMEDIATE=false` by default so no AWS/K8s
calls happen. I also ran a second pass with the Kubernetes call mocked to
prove the policy gate actually approves an action when it's supposed to,
which is different from proving the Kubernetes API call itself works - I'm
honest about that distinction if it comes up. The real IRSA-style auth in
`eks_client.py` is written and correct against the documented EKS token
protocol, but the thing that would prove it end-to-end is a `terraform apply`
against a live cluster, which I haven't done yet.

## Trade-offs I'd defend if pushed

- **EKS access entries over the aws-auth ConfigMap** - newer API, shows up
  in `terraform plan`, doesn't require fighting other editors of a shared
  YAML file.
- **Mock-first, not "fake it till I make it"** - the rule-based analyzer
  forced me to write down my actual diagnostic reasoning for each incident
  type, which is the same knowledge the real LLM prompt needed anyway.
- **Deployment name inferred from pod name** - a real limitation I'd rather
  name than hide. It's why the handler skips automated action instead of
  guessing when it can't confidently resolve namespace/deployment.
- **auto_remediate defaults to false** - I'd rather explain "I shipped this
  conservative on purpose and here's my plan to loosen it" than "I shipped
  something that could restart production the first time it misfires."

## What I'd do differently at real production scale

- Add an alarm on the DLQ depth - "the auto-remediator itself is failing"
  needs its own page, same gap I'd flag reviewing any alerting setup.
- A scale-in complement to `scale_nodegroup`, or lean on Cluster Autoscaler
  for that instead of extending this Lambda's blast radius.
- Move the mock analyzer's knowledge base into something the on-call
  rotation can edit without a code review, if it ends up being the thing
  people want to tune most often. Right now it's a Python dict, which is
  fine for a project this size and would be a real limitation at team
  scale.
- Widen the `bedrock_analyzer.py` path once I've watched the mock version
  run and trust the pipeline it's sitting behind.

## How this connects to what I actually built on the capstone

This isn't disconnected from Story 2.3 - it's the same alerting surface
(the CloudWatch alarms, the Slack delivery via Secrets Manager) with one
more layer on top. If asked what I built as alerting/on-call lead versus
what's new here: Story 2.3 is the detection and human-facing alerting;
this project is the automated-response layer sitting on top of alarms that
already existed.

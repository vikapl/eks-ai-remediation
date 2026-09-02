"""
handler.py

Lambda entry point. One job, four steps:
  1. Parse the EventBridge "CloudWatch Alarm State Change" event into an
     Incident.
  2. Ask the configured analyzer (mock or bedrock) for a Diagnosis.
  3. Decide - via the policy gate below - whether to act automatically.
  4. Post everything to Slack, always, regardless of whether it acted.

The policy gate lives here, in the handler, not inside remediate.py. That's
a deliberate choice: "is it safe to act on THIS incident" is a decision
about the incident and the current config, not a property of the action
itself, so it belongs next to the thing making the decision, not buried
inside the function that executes it.
"""
import json
import logging
import os

import config as config_module
import notify_slack
import remediate
from analyzer import get_analyzer
from models import Incident

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def lambda_handler(event, context):
    cfg = config_module.load_config()
    incident = _parse_event(event, cfg)

    analyzer = get_analyzer(
        cfg.ai_provider, bedrock_model_id=cfg.bedrock_model_id, aws_region=cfg.aws_region
    )
    diagnosis = analyzer.analyze(incident)

    # Structured log line, not a free-text one - this is the audit trail for
    # every decision this Lambda makes. If I ever need to answer "why did
    # the bot restart payments-api at 2am", this line is the answer.
    logger.info(json.dumps({
        "event": "diagnosis_complete",
        "alarm_name": incident.alarm_name,
        "cluster": incident.cluster_name,
        "namespace": incident.namespace,
        "deployment": incident.deployment,
        "root_cause": diagnosis.root_cause,
        "confidence": diagnosis.confidence,
        "remediation_type": diagnosis.remediation_type,
        "analyzer_provider": diagnosis.provider,
    }))

    action_result = _maybe_remediate(cfg, incident, diagnosis)

    message = _format_slack_message(incident, diagnosis, action_result)
    notify_slack.notify(cfg.slack_secret_arn, cfg.aws_region, message)

    return {
        "alarm_name": incident.alarm_name,
        "diagnosis": diagnosis.__dict__,
        "action": action_result,
    }


def _parse_event(event: dict, cfg) -> Incident:
    """Pulls the fields the rest of the system needs out of a CloudWatch
    Alarm State Change event. Real events (and the fixtures in
    tests/fixtures/) carry the alarm's metric dimensions under
    detail.configuration.metrics[0].metricStat.metric.dimensions."""
    detail = event.get("detail", {})
    configuration = detail.get("configuration", {})
    metrics = configuration.get("metrics", [])

    dimensions = {}
    metric_name = None
    if metrics:
        metric = metrics[0].get("metricStat", {}).get("metric", {})
        dimensions = metric.get("dimensions", {}) or {}
        metric_name = metric.get("name")

    # Container Insights alarms carry a PodName dimension, not a
    # Deployment one - ReplicaSet/Pod hash suffixes have to be stripped to
    # recover the Deployment name (payments-api-7f8d9c-abcde -> payments-api).
    # I'm calling this out because it's a real limitation, not something I'd
    # want to gloss over in an interview: a mis-parsed pod name (or a
    # StatefulSet, which doesn't have this suffix shape at all) means
    # `deployment` comes back wrong or empty, and _maybe_remediate() below
    # is written to skip automated action rather than guess when that
    # happens.
    pod_name = dimensions.get("PodName")
    deployment = dimensions.get("Deployment") or (
        _deployment_from_pod_name(pod_name) if pod_name else None
    )

    return Incident(
        alarm_name=detail.get("alarmName", "unknown-alarm"),
        alarm_description=configuration.get("description", "") or "",
        cluster_name=dimensions.get("ClusterName") or cfg.eks_cluster_name,
        namespace=dimensions.get("Namespace"),
        deployment=deployment,
        nodegroup=dimensions.get("NodegroupName"),
        metric_name=metric_name,
        region=event.get("region") or cfg.aws_region,
        account_id=event.get("account", ""),
        raw_event=event,
    )


def _deployment_from_pod_name(pod_name: str) -> str:
    parts = pod_name.split("-")
    return "-".join(parts[:-2]) if len(parts) > 2 else pod_name


def _maybe_remediate(cfg, incident: Incident, diagnosis) -> dict:
    """The policy gate. Two independent checks have to pass before any
    action runs - either one failing means recommend-only, no exceptions."""
    if not cfg.auto_remediate:
        return {
            "status": "recommend_only",
            "action": diagnosis.remediation_type,
            "detail": "AUTO_REMEDIATE is off - posting a recommendation only.",
        }

    if diagnosis.remediation_type not in cfg.allowed_auto_actions:
        return {
            "status": "recommend_only",
            "action": diagnosis.remediation_type,
            "detail": f"'{diagnosis.remediation_type}' is not in ALLOWED_AUTO_ACTIONS - posting a recommendation only.",
        }

    if diagnosis.remediation_type == "restart_deployment":
        if not incident.namespace or not incident.deployment:
            return {
                "status": "skipped",
                "action": "restart_deployment",
                "detail": "Could not determine namespace/deployment from the event - skipping automated action.",
            }
        return remediate.restart_deployment(
            incident.cluster_name, incident.region, incident.namespace, incident.deployment
        )

    if diagnosis.remediation_type == "scale_nodegroup":
        if not incident.nodegroup:
            return {
                "status": "skipped",
                "action": "scale_nodegroup",
                "detail": "Could not determine nodegroup from the event - skipping automated action.",
            }
        return remediate.scale_nodegroup(
            incident.cluster_name, incident.region, incident.nodegroup, cfg.max_nodegroup_scale_step
        )

    # manual_investigation (or anything else) never has an automated handler
    # by design - it's a signal, not an action.
    return {
        "status": "recommend_only",
        "action": diagnosis.remediation_type,
        "detail": "No automated handler for this remediation_type - posting a recommendation only.",
    }


def _format_slack_message(incident: Incident, diagnosis, action_result: dict) -> str:
    return "\n".join([
        f"*EKS incident:* `{incident.alarm_name}`",
        f"*Cluster / namespace:* {incident.cluster_name} / {incident.namespace or 'unknown'}",
        f"*Likely root cause* ({diagnosis.confidence:.0%} confidence, via {diagnosis.provider}): {diagnosis.root_cause}",
        diagnosis.explanation,
        f"*Suggested command:* `{diagnosis.suggested_command}`",
        f"*Automation:* {action_result['status']} - {action_result.get('detail', action_result.get('error', ''))}",
    ])

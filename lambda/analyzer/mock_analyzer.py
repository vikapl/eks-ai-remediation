"""
analyzer/mock_analyzer.py

A small, rule-based stand-in for a real LLM call. I built the mock first
(and it's what's actually running by default) for three reasons: it's free,
it's deterministic (so tests and demos give the same answer every time), and
writing it forced me to put into words what I actually believe about each
incident type - which is the same knowledge a real prompt to Bedrock would
need anyway (bedrock_analyzer.py's system prompt is built from the same
mental model).

It only recognizes the incident types listed below. Anything else falls
through to a low-confidence "I don't know, go look" response rather than a
confident-sounding guess - that's the honest failure mode, and it's exactly
the gap a real LLM is meant to close.
"""
import re

from analyzer.base import IncidentAnalyzer
from models import Diagnosis, Incident

# Each entry pairs a regex (matched against the alarm name + metric name +
# alarm description) with a canned diagnosis. Order matters - first match
# wins, so more specific patterns are listed before generic ones.
_KNOWLEDGE_BASE = [
    {
        "match": re.compile(r"crashloop", re.I),
        "root_cause": "Pod is stuck in CrashLoopBackOff - the container keeps exiting shortly after start.",
        "explanation": (
            "CrashLoopBackOff almost always means the container's own process is dying, not that "
            "Kubernetes can't schedule it. The two causes I'd rule out first: (1) a bad deploy - a "
            "config/env change or image tag that broke startup, and (2) the process crashing on a "
            "downstream dependency (DB, secret, feature flag) that isn't available yet. A rollout "
            "restart only clears this if the underlying cause is transient or a bad revision has "
            "already been rolled back - it is not a fix for a genuinely broken image."
        ),
        "confidence": 0.72,
        "remediation_type": "restart_deployment",
        "suggested_command": "kubectl rollout restart deployment/{deployment} -n {namespace}",
    },
    {
        "match": re.compile(r"oomkill|out.?of.?memory", re.I),
        "root_cause": "Container was OOMKilled - it exceeded its memory limit.",
        "explanation": (
            "A resource ceiling problem, not a code crash. Restarting the pod buys a few minutes but "
            "the same limit gets hit again under the same load. The real fix is almost always raising "
            "the memory `limits` in the Deployment spec, or chasing a memory leak if usage climbs over "
            "time rather than spiking with traffic - which is why I don't auto-restart for this one."
        ),
        "confidence": 0.68,
        "remediation_type": "manual_investigation",
        "suggested_command": "kubectl top pod -n {namespace} -l app={deployment} && kubectl describe deployment/{deployment} -n {namespace}",
    },
    {
        "match": re.compile(r"notready|node.?not.?ready", re.I),
        "root_cause": "One or more worker nodes report NotReady - kubelet has stopped heartbeating to the control plane.",
        "explanation": (
            "This is node-level, not pod-level. Usual suspects: the node hit disk/memory pressure and "
            "kubelet started evicting, a networking blip between kubelet and the API server, or the "
            "underlying EC2 instance is failing status checks. Adding one node gives the scheduler "
            "somewhere to move workloads while I investigate the unhealthy node directly, rather than "
            "leaving pods Pending."
        ),
        "confidence": 0.60,
        "remediation_type": "scale_nodegroup",
        "suggested_command": "aws eks update-nodegroup-config --cluster-name {cluster} --nodegroup-name {nodegroup} --scaling-config desiredSize=<current+1>",
    },
    {
        "match": re.compile(r"imagepullbackoff|errimagepull", re.I),
        "root_cause": "Kubernetes can't pull the container image - bad tag, missing image, or a registry auth problem.",
        "explanation": (
            "Not a runtime failure - the container never even starts. Check the image tag in the "
            "latest Deployment revision first (a typo'd or unpushed tag is the most common cause), "
            "then registry auth (ECR token expiry, imagePullSecrets) if the tag looks right."
        ),
        "confidence": 0.65,
        "remediation_type": "manual_investigation",
        "suggested_command": "kubectl describe pod -n {namespace} -l app={deployment} | grep -A5 Events",
    },
    {
        "match": re.compile(r"high.?cpu|cpuutilization", re.I),
        "root_cause": "Sustained high CPU on the workload or node.",
        "explanation": (
            "Could be legitimate load - worth checking if it correlates with a traffic spike - or a "
            "runaway process. I don't auto-act on this one: scaling out (HPA) and scaling up (bigger "
            "instance type) are both reasonable fixes depending on which it is, and picking wrong "
            "either burns money or papers over a real bug."
        ),
        "confidence": 0.55,
        "remediation_type": "manual_investigation",
        "suggested_command": "kubectl top pod -n {namespace} --sort-by=cpu",
    },
]

_FALLBACK = {
    "root_cause": "Alarm fired but didn't match a known incident pattern.",
    "explanation": (
        "The mock analyzer only recognizes the incident types above - for anything else, I'd rather "
        "say 'I don't know, go look' than fabricate a diagnosis. This is exactly the gap a real LLM "
        "call (AI_PROVIDER=bedrock) is meant to generalize past: it isn't limited to a fixed pattern "
        "list the way this rule-based version is."
    ),
    "confidence": 0.0,
    "remediation_type": "manual_investigation",
    "suggested_command": "kubectl describe deployment/{deployment} -n {namespace}",
}


class MockAnalyzer(IncidentAnalyzer):
    def analyze(self, incident: Incident) -> Diagnosis:
        haystack = " ".join(
            filter(None, [incident.alarm_name, incident.metric_name, incident.alarm_description])
        )
        for entry in _KNOWLEDGE_BASE:
            if entry["match"].search(haystack):
                return self._to_diagnosis(entry, incident)
        return self._to_diagnosis(_FALLBACK, incident)

    @staticmethod
    def _to_diagnosis(entry: dict, incident: Incident) -> Diagnosis:
        command = entry["suggested_command"].format(
            deployment=incident.deployment or "<deployment>",
            namespace=incident.namespace or "default",
            cluster=incident.cluster_name,
            nodegroup=incident.nodegroup or "<nodegroup>",
        )
        return Diagnosis(
            root_cause=entry["root_cause"],
            explanation=entry["explanation"],
            confidence=entry["confidence"],
            remediation_type=entry["remediation_type"],
            suggested_command=command,
            provider="mock",
        )

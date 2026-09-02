"""
remediate.py

Every function here is a concrete action, and every one of them assumes the
caller (handler.py) has already cleared two independent gates: AUTO_REMEDIATE
is true, and this specific remediation_type is in ALLOWED_AUTO_ACTIONS. This
file doesn't re-check policy - it just does the thing, as safely as I can
make a single action, and reports back exactly what happened so it can be
logged and posted to Slack either way.
"""
import logging
import time

import boto3
from kubernetes.client.exceptions import ApiException

import eks_client

logger = logging.getLogger(__name__)


def restart_deployment(cluster_name: str, region: str, namespace: str, deployment: str) -> dict:
    """Equivalent of `kubectl rollout restart deployment/<name> -n <namespace>`:
    patches the pod template with a restartedAt annotation so the Deployment
    controller replaces every pod one at a time, honoring the existing
    rollout strategy. Doesn't touch replica count or image - it can't turn a
    CrashLoopBackOff into something worse by scaling or changing what's
    deployed, only ask Kubernetes to try running the same thing again."""
    apps_v1 = eks_client.build_client(cluster_name, region)

    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        "eks-ai-remediation/triggered-by": "automated-diagnosis",
                    }
                }
            }
        }
    }

    try:
        apps_v1.patch_namespaced_deployment(name=deployment, namespace=namespace, body=patch)
    except ApiException as exc:
        logger.error("rollout restart failed for %s/%s: %s", namespace, deployment, exc)
        return {"status": "failed", "action": "restart_deployment", "error": str(exc)}

    return {
        "status": "executed",
        "action": "restart_deployment",
        "detail": f"Restarted rollout for deployment/{deployment} in namespace/{namespace}",
    }


def scale_nodegroup(cluster_name: str, region: str, nodegroup: str, max_step: int) -> dict:
    """Adds up to `max_step` nodes to a managed nodegroup's desired size,
    capped at the nodegroup's own configured maxSize. Pure AWS API call - no
    Kubernetes RBAC involved at all, which is exactly why this is the
    lower-risk of the two automatable actions: worst case, I pay for one
    extra node for a while."""
    eks = boto3.client("eks", region_name=region)

    current = eks.describe_nodegroup(clusterName=cluster_name, nodegroupName=nodegroup)["nodegroup"]
    scaling = current["scalingConfig"]
    new_desired = min(scaling["desiredSize"] + max_step, scaling["maxSize"])

    if new_desired == scaling["desiredSize"]:
        return {
            "status": "skipped",
            "action": "scale_nodegroup",
            "detail": (
                f"Nodegroup {nodegroup} is already at its configured maxSize "
                f"({scaling['maxSize']}) - not scaling further automatically."
            ),
        }

    eks.update_nodegroup_config(
        clusterName=cluster_name,
        nodegroupName=nodegroup,
        scalingConfig={"desiredSize": new_desired},
    )

    return {
        "status": "executed",
        "action": "scale_nodegroup",
        "detail": f"Scaled nodegroup {nodegroup} desired size {scaling['desiredSize']} -> {new_desired}",
    }

"""
eks_client.py

Builds a Kubernetes API client authenticated the same way `kubectl` and
`aws eks get-token` are: a presigned STS GetCallerIdentity URL, encoded into
a bearer token that EKS's built-in webhook token authenticator can verify
against IAM. This is the mechanism behind every "IAM role -> Kubernetes
identity" story on EKS, including the access entry + RBAC I set up in
terraform/eks_access.tf.

I implemented this by hand with boto3 + botocore's request signer rather
than shelling out to the AWS CLI, because the CLI isn't guaranteed to be on
the Lambda runtime's PATH - this keeps the whole auth path inside the two
Python dependencies already in requirements.txt (boto3, kubernetes).
"""
import base64

import boto3
from botocore.signers import RequestSigner
from kubernetes import client as k8s_client

# Matches aws-iam-authenticator's own default - short-lived on purpose,
# since a Lambda invocation only needs the token for the few seconds it
# takes to make one API call.
_TOKEN_TTL_SECONDS = 60
_K8S_AWS_ID_HEADER = "x-k8s-aws-id"


def _bearer_token(cluster_name: str, region: str) -> str:
    """Reproduces the token `aws eks get-token --cluster-name ...` would
    produce, without shelling out to the CLI."""
    session = boto3.session.Session()
    sts = session.client("sts", region_name=region)

    signer = RequestSigner(
        sts.meta.service_model.service_id,
        region,
        "sts",
        "v4",
        session.get_credentials(),
        session.events,
    )

    params = {
        "method": "GET",
        "url": f"https://sts.{region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
        "body": {},
        # This header is the whole trick: EKS's token authenticator checks
        # that the presigned URL was signed with this exact cluster name
        # attached, which is what scopes the token to one specific cluster
        # instead of being valid against any cluster the caller's IAM
        # credentials could reach.
        "headers": {_K8S_AWS_ID_HEADER: cluster_name},
        "context": {},
    }

    signed_url = signer.generate_presigned_url(
        params, region_name=region, expires_in=_TOKEN_TTL_SECONDS, operation_name=""
    )

    # EKS expects the "k8s-aws-v1." prefix and unpadded base64url encoding -
    # exactly what aws-iam-authenticator produces before handing the token
    # to the API server's webhook authenticator.
    encoded = base64.urlsafe_b64encode(signed_url.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"k8s-aws-v1.{encoded}"


def _write_ca_cert(b64_data: str) -> str:
    """The kubernetes client library wants the CA cert as a file path, not
    raw bytes - Lambda's writable /tmp is the only place in the execution
    environment I can put it."""
    path = "/tmp/eks-ca.pem"
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64_data))
    return path


def build_client(cluster_name: str, region: str) -> k8s_client.AppsV1Api:
    """Returns a ready-to-use Kubernetes AppsV1Api client scoped to the
    given EKS cluster. AppsV1Api (not CoreV1Api) because the only write
    action this project performs - restart_deployment - patches a
    Deployment object, which lives in the apps/v1 API group."""
    eks = boto3.client("eks", region_name=region)
    cluster = eks.describe_cluster(name=cluster_name)["cluster"]

    configuration = k8s_client.Configuration()
    configuration.host = cluster["endpoint"]
    configuration.verify_ssl = True
    configuration.ssl_ca_cert = _write_ca_cert(cluster["certificateAuthority"]["data"])
    configuration.api_key = {"authorization": f"Bearer {_bearer_token(cluster_name, region)}"}

    return k8s_client.AppsV1Api(k8s_client.ApiClient(configuration))

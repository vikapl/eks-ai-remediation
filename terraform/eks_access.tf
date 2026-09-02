# eks_access.tf
# Grants the remediation Lambda's IAM role a narrow, native-Kubernetes-RBAC
# identity inside the cluster - not cluster-admin, not even namespace-admin.
# It can only get/list/patch Deployments in the namespaces I name below.
#
# I'm using EKS "access entries" (the newer AWS API) instead of hand-editing
# the aws-auth ConfigMap. The old ConfigMap approach means cluster access is
# a YAML edit that Terraform can't safely manage without fighting other
# writers; access entries are a first-class AWS resource, so this whole
# grant is visible in `terraform plan` like everything else in this repo.

# 1. Tell EKS that this IAM role is allowed to authenticate to the cluster
#    at all, and map it to a Kubernetes username. type = "STANDARD" with no
#    associated AWS-managed access policy means: "let this identity in the
#    door, but grant it zero permissions by default" - the permissions come
#    entirely from the Role/RoleBinding below.
resource "aws_eks_access_entry" "remediation_lambda" {
  cluster_name  = var.eks_cluster_name
  principal_arn = aws_iam_role.remediation_lambda.arn
  type          = "STANDARD"

  kubernetes_groups = ["eks-ai-remediation-bot"]

  tags = var.tags
}

# 2. Native Kubernetes RBAC: what "eks-ai-remediation-bot" can actually do.
#    Scoped to a couple of namespaces I'm willing to let this bot touch -
#    NOT cluster-wide. Extend the for_each set as I trust it with more.
locals {
  remediation_namespaces = ["default", "payments"]
}

resource "kubernetes_role" "deployment_restart" {
  for_each = toset(local.remediation_namespaces)

  metadata {
    name      = "eks-ai-remediation-restart"
    namespace = each.value
  }

  # get/list so the Lambda can confirm the Deployment exists and read its
  # current pod template before patching it; patch is the only write verb -
  # it can restart a rollout, it cannot delete or create anything.
  rule {
    api_groups = ["apps"]
    resources  = ["deployments"]
    verbs      = ["get", "list", "patch"]
  }

  # Read-only visibility into Pods, so a future version of the analyzer
  # could pull pod status/events for a richer diagnosis without needing a
  # separate permission grant.
  rule {
    api_groups = [""]
    resources  = ["pods", "pods/log"]
    verbs      = ["get", "list"]
  }
}

resource "kubernetes_role_binding" "deployment_restart" {
  for_each = toset(local.remediation_namespaces)

  metadata {
    name      = "eks-ai-remediation-restart"
    namespace = each.value
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role.deployment_restart[each.value].metadata[0].name
  }

  subject {
    kind      = "Group"
    name      = "eks-ai-remediation-bot"
    api_group = "rbac.authorization.k8s.io"
  }
}

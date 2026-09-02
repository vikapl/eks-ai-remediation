# iam.tf
# The Lambda's execution role - what it's allowed to do, and just as
# important, what it's NOT allowed to do. I scoped every statement to a
# specific ARN rather than "*" wherever AWS's API lets me, because this
# role can eventually touch production workloads and I want the blast
# radius of a compromised or buggy Lambda to be small.

data "aws_caller_identity" "current" {}

# The trust policy: only the Lambda service itself may assume this role.
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "remediation_lambda" {
  name               = "eks-ai-remediation-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

# --- CloudWatch Logs ---------------------------------------------------
# Standard Lambda logging permissions, scoped to this function's own log
# group rather than every log group in the account.
data "aws_iam_policy_document" "logs" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/eks-ai-remediation-${var.environment}:*"
    ]
  }
}

# --- Reading the incident / talking to EKS ------------------------------
# DescribeCluster: needed to fetch the cluster's API endpoint + CA cert so
# the Lambda can build a Kubernetes API client (see eks_client.py).
# DescribeNodegroup / UpdateNodegroupConfig: the AWS-native side of the
# "scale a nodegroup" remediation - no Kubernetes RBAC needed for that one,
# it's a pure AWS API call.
data "aws_iam_policy_document" "eks" {
  statement {
    effect  = "Allow"
    actions = ["eks:DescribeCluster"]
    resources = [
      "arn:aws:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:cluster/${var.eks_cluster_name}"
    ]
  }

  statement {
    effect  = "Allow"
    actions = ["eks:DescribeNodegroup", "eks:UpdateNodegroupConfig"]
    resources = [
      "arn:aws:eks:${var.aws_region}:${data.aws_caller_identity.current.account_id}:nodegroup/${var.eks_cluster_name}/*/*"
    ]
  }
}

# --- Slack notification --------------------------------------------------
data "aws_iam_policy_document" "secrets" {
  statement {
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [var.slack_webhook_secret_arn]
  }
}

# --- Optional Bedrock call ------------------------------------------------
# Only meaningful when ai_provider = "bedrock". Scoped to the single model
# ID this stack is configured to call, not "bedrock:*".
data "aws_iam_policy_document" "bedrock" {
  count = var.ai_provider == "bedrock" ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["bedrock:InvokeModel"]
    resources = [
      "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"
    ]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "logs"
  role   = aws_iam_role.remediation_lambda.id
  policy = data.aws_iam_policy_document.logs.json
}

resource "aws_iam_role_policy" "eks" {
  name   = "eks-read-and-scale"
  role   = aws_iam_role.remediation_lambda.id
  policy = data.aws_iam_policy_document.eks.json
}

resource "aws_iam_role_policy" "secrets" {
  name   = "slack-secret-read"
  role   = aws_iam_role.remediation_lambda.id
  policy = data.aws_iam_policy_document.secrets.json
}

resource "aws_iam_role_policy" "bedrock" {
  count  = var.ai_provider == "bedrock" ? 1 : 0
  name   = "bedrock-invoke"
  role   = aws_iam_role.remediation_lambda.id
  policy = data.aws_iam_policy_document.bedrock[0].json
}

# Note: I deliberately did NOT attach any Kubernetes-object permission here.
# The IAM role above only gets the Lambda in the door to the EKS control
# plane (via DescribeCluster + an EKS access entry, see eks_access.tf).
# What it's allowed to *do* once inside the cluster - get/list/patch on
# Deployments, and only in specific namespaces - is enforced by native
# Kubernetes RBAC, not IAM. Two independent permission systems have to agree
# before this Lambda can touch a workload.

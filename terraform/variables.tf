# variables.tf
# Every knob this module needs, with no hardcoded values in main logic.
# This is the same lesson I got from Pankaj's review on Story 2.3: thresholds
# and names belong in variables, not baked into resource bodies.

variable "aws_region" {
  description = "AWS region the EKS cluster and this remediation stack live in."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used for naming/tagging (e.g. dev, staging)."
  type        = string
  default     = "dev"
}

variable "eks_cluster_name" {
  description = "Name of the EKS cluster this responder watches and can act on."
  type        = string
}

variable "alarm_name_prefix" {
  description = <<-EOT
    Only CloudWatch alarms whose name starts with this prefix will trigger
    the remediation Lambda. I scope this deliberately - the EventBridge rule
    should never see alarms outside the EKS-incident family (e.g. billing
    alarms), even if the Lambda's own filtering would also catch it. Two
    layers of narrowing beats one.
  EOT
  type    = string
  default = "eks-"
}

variable "slack_webhook_secret_arn" {
  description = <<-EOT
    ARN of the Secrets Manager secret holding the Slack webhook URL - the
    same secret pattern I used for alarm delivery in Story 2.3, reused here
    rather than inventing a second way to talk to Slack.
  EOT
  type = string
}

variable "ai_provider" {
  description = "Which incident analyzer the Lambda uses: 'mock' (rule-based, free) or 'bedrock' (real LLM call, has cost)."
  type        = string
  default     = "mock"

  validation {
    condition     = contains(["mock", "bedrock"], var.ai_provider)
    error_message = "ai_provider must be either \"mock\" or \"bedrock\"."
  }
}

variable "bedrock_model_id" {
  description = "Bedrock model ID to call when ai_provider = \"bedrock\". Ignored otherwise."
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20241022-v2:0"
}

variable "auto_remediate" {
  description = <<-EOT
    Master safety switch. false = the Lambda only diagnoses and posts a
    recommendation to Slack (a human clicks "run" themselves). true = the
    Lambda is also allowed to take action, but ONLY for alarm types listed
    in allowed_auto_actions. Defaults to false on purpose - I don't want a
    misclassified incident to touch production before I've watched this run
    in observe-only mode for a while.
  EOT
  type    = bool
  default = false
}

variable "allowed_auto_actions" {
  description = <<-EOT
    Allow-list of remediation_type values the Lambda may act on automatically
    when auto_remediate is true. Anything not in this list is always
    recommend-only, no matter how confident the analyzer is. This is the
    single most important safety control in the whole stack.
  EOT
  type    = list(string)
  default = ["restart_deployment"]
}

variable "max_nodegroup_scale_step" {
  description = "Largest number of extra nodes the Lambda may add to a nodegroup in one remediation (scale_nodegroup action)."
  type        = number
  default     = 1
}

variable "log_retention_days" {
  description = "How long to keep the Lambda's CloudWatch Logs."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Common resource tags."
  type        = map(string)
  default = {
    Project   = "eks-ai-remediation"
    ManagedBy = "terraform"
  }
}

# lambda.tf
# The responder function itself, plus the operational bits around it that
# make it trustworthy: structured logging with a retention policy, and a
# dead-letter queue so a failed invocation doesn't just vanish.

# Zips up the lambda/ source directory at plan/apply time. For a project
# this size a plain archive is the right call; if this grew past a handful
# of files I'd move to a container image or a build step in CI instead.
data "archive_file" "lambda_package" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/build/lambda.zip"
  excludes    = ["__pycache__"]
}

resource "aws_cloudwatch_log_group" "remediation_lambda" {
  name              = "/aws/lambda/eks-ai-remediation-${var.environment}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# Dead-letter queue: if the Lambda throws (bad event shape, AWS API hiccup,
# whatever) after exhausting its retries, the event lands here instead of
# disappearing. An alarm on this queue's depth is the natural next thing
# I'd wire up - "the auto-remediator itself is failing" deserves its own
# page, same as any other alerting gap I'd flag on Story 2.3.
resource "aws_sqs_queue" "remediation_dlq" {
  name                      = "eks-ai-remediation-dlq-${var.environment}"
  message_retention_seconds = 1209600 # 14 days
  tags                      = var.tags
}

resource "aws_lambda_function" "remediation" {
  function_name = "eks-ai-remediation-${var.environment}"
  role          = aws_iam_role.remediation_lambda.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 256

  filename         = data.archive_file.lambda_package.output_path
  source_code_hash = data.archive_file.lambda_package.output_base64sha256

  dead_letter_config {
    target_arn = aws_sqs_queue.remediation_dlq.arn
  }

  environment {
    variables = {
      AI_PROVIDER             = var.ai_provider
      BEDROCK_MODEL_ID        = var.bedrock_model_id
      AUTO_REMEDIATE          = tostring(var.auto_remediate)
      ALLOWED_AUTO_ACTIONS    = join(",", var.allowed_auto_actions)
      EKS_CLUSTER_NAME        = var.eks_cluster_name
      SLACK_SECRET_ARN        = var.slack_webhook_secret_arn
      MAX_NODEGROUP_SCALE_STEP = tostring(var.max_nodegroup_scale_step)
      LOG_LEVEL                = "INFO"
    }
  }

  tags = var.tags

  depends_on = [
    aws_iam_role_policy.logs,
    aws_cloudwatch_log_group.remediation_lambda,
  ]
}

# Lets EventBridge invoke this function. Without this resource-based policy
# statement, the EventBridge rule in eventbridge.tf would fail silently -
# it would "successfully" match events and just never reach the Lambda.
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.remediation.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.eks_alarm_state_change.arn
}

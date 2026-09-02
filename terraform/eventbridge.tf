# eventbridge.tf
# The trigger. CloudWatch alarms (the ones from Story 2.3) already publish a
# "CloudWatch Alarm State Change" event to the account's default event bus
# every time they change state - I don't need to configure the alarms
# themselves to "send" anything, EventBridge is already listening account-
# wide. This rule just picks out the ones I care about.

resource "aws_cloudwatch_event_rule" "eks_alarm_state_change" {
  name        = "eks-ai-remediation-trigger-${var.environment}"
  description = "Fires the AI remediation Lambda when an eks-* CloudWatch alarm enters ALARM state."

  # event pattern = a filter, not a transformation. AWS matches this
  # structurally against every event on the bus; only events that match
  # every field here get delivered to the target.
  event_pattern = jsonencode({
    source      = ["aws.cloudwatch"]
    detail-type = ["CloudWatch Alarm State Change"]
    detail = {
      # Only alarms whose name starts with the configured prefix (default
      # "eks-") - keeps this rule scoped to the EKS-incident alarm family
      # even as more, unrelated alarms get added to the account later.
      alarmName = [{ prefix = var.alarm_name_prefix }]
      state = {
        value = ["ALARM"]
      }
    }
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "invoke_remediation_lambda" {
  rule = aws_cloudwatch_event_rule.eks_alarm_state_change.name
  arn  = aws_lambda_function.remediation.arn

  # If the Lambda invocation itself fails (throttled, EventBridge-side
  # error - distinct from the Lambda's own DLQ, which only catches
  # execution failures), retry twice over 10 minutes before giving up.
  retry_policy {
    maximum_retry_attempts       = 2
    maximum_event_age_in_seconds = 600
  }
}

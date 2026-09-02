# outputs.tf
# What a teammate (or future me) would want to see right after `apply`.

output "lambda_function_name" {
  description = "Name of the deployed remediation Lambda."
  value       = aws_lambda_function.remediation.function_name
}

output "lambda_function_arn" {
  value = aws_lambda_function.remediation.arn
}

output "eventbridge_rule_arn" {
  value = aws_cloudwatch_event_rule.eks_alarm_state_change.arn
}

output "dead_letter_queue_url" {
  description = "SQS queue holding any invocations the Lambda failed to process."
  value       = aws_sqs_queue.remediation_dlq.id
}

output "lambda_role_arn" {
  description = "IAM role ARN - also the principal_arn registered as an EKS access entry."
  value       = aws_iam_role.remediation_lambda.arn
}

"""
notify_slack.py

Reuses the Secrets-Manager-backed Slack webhook pattern from Story 2.3 -
same secret, same delivery mechanism - rather than inventing a second way to
talk to Slack for this project.

When SLACK_SECRET_ARN isn't set (every local run and every test), this
prints the notification instead of making a network call. That's what lets
tests/local_test.py exercise the full handler, including the "notify"
step, with zero AWS credentials and zero network access required.
"""
import json
import logging
import urllib.request

import boto3

logger = logging.getLogger(__name__)


def _fetch_webhook_url(secret_arn: str, region: str) -> str:
    client = boto3.client("secretsmanager", region_name=region)
    secret = client.get_secret_value(SecretId=secret_arn)
    return secret["SecretString"]


def notify(secret_arn: str, region: str, message: str) -> None:
    if not secret_arn:
        logger.info("SLACK_SECRET_ARN not set - printing notification instead of sending:\n%s", message)
        print(message)
        return

    webhook_url = _fetch_webhook_url(secret_arn, region)
    body = json.dumps({"text": message}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        if response.status >= 300:
            logger.error("Slack webhook returned unexpected status %s", response.status)

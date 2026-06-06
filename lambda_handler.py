"""AWS Lambda entry point for the paper trading tick.

Deploy this function and trigger it with an EventBridge rule on a schedule
(e.g. "rate(1 minute)") to replace the local infinite polling loop.

Required environment variables on the Lambda function:
  STATE_TABLE      – DynamoDB table for portfolio state  (e.g. quant-paper-state)
  TRADES_TABLE     – DynamoDB table for trade history    (e.g. quant-trades)
  CACHE_BUCKET     – S3 bucket for parquet cache         (e.g. my-quant-cache)
  ALERT_TOPIC_ARN  – SNS topic ARN for trade alerts
  CW_LOG_GROUP     – CloudWatch log group  (e.g. /quant/paper-trader)

The Lambda execution role needs the IAM policy in aws/iam_policy.json.
"""

from config import UNIVERSE
from paper_trader.trader import _tick, load_state, save_state


def handler(event, context):
    state = load_state()
    _tick(state, UNIVERSE)
    save_state(state)
    return {"statusCode": 200, "body": "tick complete"}

#!/usr/bin/env bash
# One-time AWS infrastructure setup for Quant_trader.
# Edit the variables below, then run:  bash aws/setup.sh
#
# Prerequisites: AWS CLI configured (aws configure), and an IAM user/role
# with permissions to create S3, DynamoDB, SNS, Lambda, EventBridge resources.

set -euo pipefail

# ── Configuration — edit these ────────────────────────────────────────────────
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
CACHE_BUCKET="quant-cache-${ACCOUNT_ID}"   # must be globally unique
TABLE_NAME="quant-paper-state"
SNS_TOPIC="quant-alerts"
ALERT_EMAIL="your@email.com"               # change this
LAMBDA_FUNCTION="quant-paper-trader"
LAMBDA_ROLE="quant-paper-trader-role"
LOG_GROUP="/quant/paper-trader"
# ─────────────────────────────────────────────────────────────────────────────

echo "=== Setting up Quant_trader AWS infrastructure in ${REGION} ==="

# 1. S3 bucket for parquet cache + backtest reports
echo "→ Creating S3 bucket: ${CACHE_BUCKET}"
if [ "${REGION}" = "us-east-1" ]; then
  aws s3api create-bucket --bucket "${CACHE_BUCKET}" --region "${REGION}"
else
  aws s3api create-bucket --bucket "${CACHE_BUCKET}" --region "${REGION}" \
    --create-bucket-configuration LocationConstraint="${REGION}"
fi
aws s3api put-public-access-block --bucket "${CACHE_BUCKET}" \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# 2. DynamoDB table for paper trading state
echo "→ Creating DynamoDB table: ${TABLE_NAME}"
aws dynamodb create-table \
  --table-name "${TABLE_NAME}" \
  --attribute-definitions AttributeName=pk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "${REGION}"

# 3. SNS topic for trade alerts
echo "→ Creating SNS topic: ${SNS_TOPIC}"
TOPIC_ARN=$(aws sns create-topic --name "${SNS_TOPIC}" --region "${REGION}" \
  --query TopicArn --output text)
echo "   Topic ARN: ${TOPIC_ARN}"

echo "→ Subscribing ${ALERT_EMAIL} to alerts"
aws sns subscribe --topic-arn "${TOPIC_ARN}" --protocol email \
  --notification-endpoint "${ALERT_EMAIL}" --region "${REGION}"
echo "   Check your email to confirm the SNS subscription."

# 4. CloudWatch log group
echo "→ Creating CloudWatch log group: ${LOG_GROUP}"
aws logs create-log-group --log-group-name "${LOG_GROUP}" --region "${REGION}" || true

# 5. IAM role for Lambda
echo "→ Creating IAM role: ${LAMBDA_ROLE}"
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'
ROLE_ARN=$(aws iam create-role \
  --role-name "${LAMBDA_ROLE}" \
  --assume-role-policy-document "${TRUST_POLICY}" \
  --query Role.Arn --output text)
echo "   Role ARN: ${ROLE_ARN}"

# Substitute the actual bucket name into the policy before attaching
sed "s/YOUR_CACHE_BUCKET/${CACHE_BUCKET}/g" aws/iam_policy.json > /tmp/quant_policy.json
aws iam put-role-policy \
  --role-name "${LAMBDA_ROLE}" \
  --policy-name quant-paper-trader-policy \
  --policy-document file:///tmp/quant_policy.json

# AWS managed policy for basic Lambda execution (CloudWatch Logs)
aws iam attach-role-policy \
  --role-name "${LAMBDA_ROLE}" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

echo "→ Waiting for IAM role to propagate..."
sleep 15

# 6. Package and deploy Lambda
echo "→ Packaging Lambda deployment zip"
pip install --quiet -r requirements.txt -t /tmp/lambda_pkg
cp -r . /tmp/lambda_pkg/
cd /tmp/lambda_pkg && zip -r /tmp/quant_lambda.zip . -x "*.git*" "data/cache/*" > /dev/null
cd - > /dev/null

echo "→ Creating Lambda function: ${LAMBDA_FUNCTION}"
aws lambda create-function \
  --function-name "${LAMBDA_FUNCTION}" \
  --runtime python3.12 \
  --role "${ROLE_ARN}" \
  --handler lambda_handler.handler \
  --zip-file fileb:///tmp/quant_lambda.zip \
  --timeout 300 \
  --memory-size 512 \
  --environment "Variables={
    CACHE_BUCKET=${CACHE_BUCKET},
    STATE_TABLE=${TABLE_NAME},
    ALERT_TOPIC_ARN=${TOPIC_ARN},
    CW_LOG_GROUP=${LOG_GROUP}
  }" \
  --region "${REGION}"

LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${LAMBDA_FUNCTION}"

# 7. EventBridge rule to trigger every minute
echo "→ Creating EventBridge schedule (every 1 minute)"
aws events put-rule \
  --name quant-paper-tick \
  --schedule-expression "rate(1 minute)" \
  --state ENABLED \
  --region "${REGION}"

aws lambda add-permission \
  --function-name "${LAMBDA_FUNCTION}" \
  --statement-id EventBridgeTrigger \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/quant-paper-tick" \
  --region "${REGION}"

aws events put-targets \
  --rule quant-paper-tick \
  --targets "Id=1,Arn=${LAMBDA_ARN}" \
  --region "${REGION}"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Resources created:"
echo "  S3 bucket   : ${CACHE_BUCKET}"
echo "  DynamoDB    : ${TABLE_NAME}"
echo "  SNS topic   : ${TOPIC_ARN}"
echo "  Lambda      : ${LAMBDA_FUNCTION}"
echo "  EventBridge : quant-paper-tick (every 1 minute)"
echo "  CloudWatch  : ${LOG_GROUP}"
echo ""
echo "Set these env vars to use AWS features locally:"
echo "  export CACHE_BUCKET=${CACHE_BUCKET}"
echo "  export STATE_TABLE=${TABLE_NAME}"
echo "  export ALERT_TOPIC_ARN=${TOPIC_ARN}"
echo "  export CW_LOG_GROUP=${LOG_GROUP}"

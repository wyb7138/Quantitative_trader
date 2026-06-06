#!/usr/bin/env bash
# Run the Quant Trader dashboard locally against the AWS-hosted state
# (DynamoDB tables + S3 cache created by aws/setup.sh).
#
# Usage:
#   bash run_local.sh                 # serve on http://127.0.0.1:5000
#   bash run_local.sh --port 8080     # any `main.py web` flags pass through
#
# To run in pure-local mode instead (on-disk files, no AWS), just use
# `python main.py web` directly without this script.

set -uo pipefail

# Region where aws/setup.sh created the resources. Override by exporting
# AWS_DEFAULT_REGION before running. Defaults to us-east-1 so a mismatched
# CLI default region can't point the app at the wrong place.
: "${AWS_DEFAULT_REGION:=us-east-1}"
export AWS_DEFAULT_REGION

export STATE_TABLE="${STATE_TABLE:-quant-paper-state}"
export TRADES_TABLE="${TRADES_TABLE:-quant-trades}"

# Derive the cache bucket from the account ID (matches aws/setup.sh), unless
# CACHE_BUCKET is already set.
if [ -z "${CACHE_BUCKET:-}" ]; then
  ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
  if [ -n "${ACCOUNT_ID}" ] && [ "${ACCOUNT_ID}" != "None" ]; then
    export CACHE_BUCKET="quant-cache-${ACCOUNT_ID}"
  else
    echo "  Warning: could not resolve AWS account ID — is the AWS CLI configured?" >&2
  fi
fi

echo "  Region : ${AWS_DEFAULT_REGION}"
echo "  State  : ${STATE_TABLE}"
echo "  Trades : ${TRADES_TABLE}"
echo "  Cache  : ${CACHE_BUCKET:-<unset>}"
echo ""

exec python main.py web "$@"

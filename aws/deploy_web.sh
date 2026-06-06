#!/usr/bin/env bash
# Deploy the Quant Trader web dashboard to AWS App Runner.
# Edit the variables below, then run:  bash aws/deploy_web.sh
# Safe to re-run — creates missing resources and redeploys the image.
#
# Prerequisites:
#   - aws/setup.sh has been run (creates the DynamoDB tables + S3 cache the
#     dashboard reads from)
#   - AWS CLI configured (aws configure)
#   - Docker installed and running (the image is built locally and pushed)
#
# What this creates:
#   - ECR repository holding the dashboard image
#   - IAM "ECR access role"  (lets App Runner pull the image)
#   - IAM "instance role"    (lets the running container reach DynamoDB / S3,
#                             using the existing aws/iam_policy.json)
#   - App Runner service serving the dashboard over HTTPS

set -uo pipefail
export AWS_PAGER=""

# ── Configuration — edit these ────────────────────────────────────────────────
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Must match the values created by aws/setup.sh
CACHE_BUCKET="quant-cache-${ACCOUNT_ID}"
STATE_TABLE="quant-paper-state"
TRADES_TABLE="quant-trades"

ECR_REPO="quant-web"
SERVICE_NAME="quant-web"
ECR_ACCESS_ROLE="quant-web-ecr-access-role"
INSTANCE_ROLE="quant-web-instance-role"
CPU="256"       # 0.25 vCPU
MEMORY="512"    # 0.5 GB
# ─────────────────────────────────────────────────────────────────────────────

IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}:latest"

echo "=== Deploying Quant Trader web dashboard to App Runner (${REGION}) ==="

# Helper: ensure an IAM role exists with the given trust policy; echo its ARN.
ensure_role() {
  local name="$1" trust="$2"
  if ! aws iam get-role --role-name "$name" >/dev/null 2>&1; then
    aws iam create-role --role-name "$name" \
      --assume-role-policy-document "$trust" >/dev/null
  fi
  aws iam get-role --role-name "$name" --query Role.Arn --output text
}

# 1. ECR repository
echo "→ ECR repository: ${ECR_REPO}"
aws ecr describe-repositories --repository-names "${ECR_REPO}" --region "${REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${ECR_REPO}" --region "${REGION}" >/dev/null

# 2. Build and push the image
echo "→ Building Docker image"
docker build -t "${ECR_REPO}:latest" .
echo "→ Logging in to ECR and pushing"
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
docker tag "${ECR_REPO}:latest" "${IMAGE_URI}"
docker push "${IMAGE_URI}"

# 3. ECR access role — App Runner pulls the image with this
echo "→ IAM ECR access role: ${ECR_ACCESS_ROLE}"
TRUST_ECR='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"build.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
ECR_ACCESS_ROLE_ARN=$(ensure_role "${ECR_ACCESS_ROLE}" "${TRUST_ECR}")
aws iam attach-role-policy --role-name "${ECR_ACCESS_ROLE}" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess 2>/dev/null || true

# 4. Instance role — the running container assumes this to reach DynamoDB / S3
echo "→ IAM instance role: ${INSTANCE_ROLE}"
TRUST_TASKS='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"tasks.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
INSTANCE_ROLE_ARN=$(ensure_role "${INSTANCE_ROLE}" "${TRUST_TASKS}")
sed "s/YOUR_CACHE_BUCKET/${CACHE_BUCKET}/g" aws/iam_policy.json > /tmp/quant_web_policy.json
aws iam put-role-policy --role-name "${INSTANCE_ROLE}" \
  --policy-name quant-web-policy \
  --policy-document file:///tmp/quant_web_policy.json

echo "→ Waiting for IAM roles to propagate..."
sleep 15

# 5. App Runner service
SOURCE_CFG=$(cat <<JSON
{
  "ImageRepository": {
    "ImageIdentifier": "${IMAGE_URI}",
    "ImageRepositoryType": "ECR",
    "ImageConfiguration": {
      "Port": "8080",
      "RuntimeEnvironmentVariables": {
        "STATE_TABLE": "${STATE_TABLE}",
        "TRADES_TABLE": "${TRADES_TABLE}",
        "CACHE_BUCKET": "${CACHE_BUCKET}"
      }
    }
  },
  "AutoDeploymentsEnabled": true,
  "AuthenticationConfiguration": { "AccessRoleArn": "${ECR_ACCESS_ROLE_ARN}" }
}
JSON
)
INSTANCE_CFG="{\"Cpu\":\"${CPU}\",\"Memory\":\"${MEMORY}\",\"InstanceRoleArn\":\"${INSTANCE_ROLE_ARN}\"}"
HEALTH_CFG='{"Protocol":"HTTP","Path":"/api/health","Interval":10,"Timeout":5,"HealthyThreshold":1,"UnhealthyThreshold":5}'

SERVICE_ARN=$(aws apprunner list-services --region "${REGION}" \
  --query "ServiceSummaryList[?ServiceName=='${SERVICE_NAME}'].ServiceArn | [0]" --output text)

if [ "${SERVICE_ARN}" != "None" ] && [ -n "${SERVICE_ARN}" ]; then
  echo "→ App Runner service exists — triggering a new deployment"
  # Image was just pushed to :latest; AutoDeployments will pick it up, but
  # kick a deployment explicitly so the run is deterministic.
  aws apprunner start-deployment --service-arn "${SERVICE_ARN}" --region "${REGION}" >/dev/null
else
  echo "→ Creating App Runner service: ${SERVICE_NAME}"
  SERVICE_ARN=$(aws apprunner create-service \
    --service-name "${SERVICE_NAME}" \
    --source-configuration "${SOURCE_CFG}" \
    --instance-configuration "${INSTANCE_CFG}" \
    --health-check-configuration "${HEALTH_CFG}" \
    --region "${REGION}" \
    --query 'Service.ServiceArn' --output text)
fi

SERVICE_URL=$(aws apprunner describe-service --service-arn "${SERVICE_ARN}" \
  --region "${REGION}" --query 'Service.ServiceUrl' --output text)

echo ""
echo "=== Deploy initiated ==="
echo "  Service : ${SERVICE_NAME}"
echo "  Image   : ${IMAGE_URI}"
echo "  URL     : https://${SERVICE_URL}"
echo ""
echo "App Runner is building/rolling out now (a few minutes the first time)."
echo "Track status with:"
echo "  aws apprunner describe-service --service-arn ${SERVICE_ARN} \\"
echo "    --region ${REGION} --query 'Service.Status' --output text"
echo ""
echo "NOTE: the dashboard URL is public and unauthenticated.  Put it behind"
echo "auth (custom domain + Cognito/WAF) or restrict access before exposing"
echo "real trading data."

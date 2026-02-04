import os
import json
import logging
from typing import Any, Dict
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
APPROVAL_API_ENDPOINT = os.environ.get("APPROVAL_API_ENDPOINT", "")
DDB_TABLE = os.environ.get("DDB_TABLE", "contract_approvals")

sns = boto3.client("sns", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DDB_TABLE)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Approval Lambda handler with Step Functions callback pattern.

    This function:
    1. Receives approval request with task_token from Step Functions
    2. Stores the approval request in DynamoDB
    3. Sends email/SNS notification to approvers with approval link
    4. Returns immediately (Step Functions waits for callback)

    The actual approval/rejection happens via separate API/Lambda that calls:
    step_functions.send_task_success(taskToken=task_token, output=json.dumps(result))
    or
    step_functions.send_task_failure(taskToken=task_token, error='Rejected', cause='...')

    Input:
      {
        "task_token": "...",  # Step Functions task token
        "approval_data": {
          "contract_id": "...",
          "s3_location": "...",
          "risk_flag": "HIGH_RISK" | "OK",
          "risk_scores": {...},
          "summary": "...",
          "extracted_clauses": {...}
        },
        "execution_name": "...",
        "execution_id": "..."
      }
    """
    logger.info(f"[handler] Starting approval workflow for execution: {event.get('execution_name')}")

    task_token = event.get("task_token")
    approval_data = event.get("approval_data", {})
    execution_name = event.get("execution_name")
    execution_id = event.get("execution_id")

    contract_id = approval_data.get("contract_id")

    if not task_token:
        raise ValueError("Missing task_token from Step Functions")

    if not contract_id:
        raise ValueError("Missing contract_id in approval_data")

    # Store approval request in DynamoDB
    approval_id = f"{contract_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    try:
        table.put_item(
            Item={
                "approval_id": approval_id,
                "contract_id": contract_id,
                "task_token": task_token,
                "execution_name": execution_name,
                "execution_id": execution_id,
                "approval_data": approval_data,
                "status": "PENDING",
                "created_at": datetime.utcnow().isoformat(),
                "ttl": int(datetime.utcnow().timestamp()) + (7 * 24 * 60 * 60)  # 7 days
            }
        )
        logger.info(f"[handler] Stored approval request in DynamoDB: {approval_id}")
    except ClientError as e:
        logger.error(f"[handler] Failed to store approval in DynamoDB: {e}")
        raise

    # Build approval notification message
    approval_url = f"{APPROVAL_API_ENDPOINT}/approve?approval_id={approval_id}"
    rejection_url = f"{APPROVAL_API_ENDPOINT}/reject?approval_id={approval_id}"

    risk_scores = approval_data.get("risk_scores", {})

    message = f"""
CONTRACT APPROVAL REQUIRED

Contract ID: {contract_id}
S3 Location: {approval_data.get('s3_location')}
Risk Level: {approval_data.get('risk_flag')}

RISK SCORES:
- Overall Risk: {risk_scores.get('overall', 'N/A')}/10
- Liability Risk: {risk_scores.get('liability', 'N/A')}/10
- Termination Risk: {risk_scores.get('termination', 'N/A')}/10
- Financial Risk: {risk_scores.get('financial', 'N/A')}/10

EXECUTIVE SUMMARY:
{approval_data.get('summary', 'N/A')}

RISK RATIONALE:
{approval_data.get('rationale', 'N/A')}

KEY CLAUSES:
{json.dumps(approval_data.get('extracted_clauses', {}), indent=2)}

---

ACTION REQUIRED:
To approve this contract, click: {approval_url}
To reject this contract, click: {rejection_url}

This approval request will expire in 7 days.

Approval ID: {approval_id}
Execution: {execution_name}
"""

    # Send SNS notification to approvers
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Contract Approval Required: {contract_id} [{approval_data.get('risk_flag')}]",
            Message=message
        )
        logger.info(f"[handler] Sent approval notification via SNS for contract {contract_id}")
    except ClientError as e:
        logger.error(f"[handler] Failed to send SNS notification: {e}")
        # Don't fail the function if notification fails

    # Return immediately - Step Functions will wait for callback
    response = {
        "approval_id": approval_id,
        "contract_id": contract_id,
        "status": "PENDING",
        "message": "Approval request sent to reviewers"
    }

    logger.info(f"[handler] Approval workflow initiated successfully for {contract_id}")
    return response

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
DDB_TABLE = os.environ.get("DDB_TABLE", "contract_approvals")

step_functions = boto3.client("stepfunctions", region_name=AWS_REGION)
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DDB_TABLE)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Callback handler for processing approval/rejection decisions.

    This Lambda is invoked via API Gateway when a user clicks approve/reject link.
    It retrieves the task_token from DynamoDB and sends the decision back to Step Functions.

    Input (API Gateway event):
      {
        "queryStringParameters": {
          "approval_id": "...",
          "decision": "APPROVED" | "REJECTED",
          "approver": "user@example.com",
          "comments": "optional comments"
        }
      }
    """
    logger.info(f"[handler] Processing approval callback")

    # Parse input from API Gateway
    query_params = event.get("queryStringParameters", {})
    approval_id = query_params.get("approval_id")
    decision = query_params.get("decision", "").upper()
    approver = query_params.get("approver", "Unknown")
    comments = query_params.get("comments", "")

    if not approval_id:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Missing approval_id parameter"})
        }

    if decision not in ["APPROVED", "REJECTED"]:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Decision must be APPROVED or REJECTED"})
        }

    # Retrieve approval request from DynamoDB
    try:
        response = table.get_item(Key={"approval_id": approval_id})
        if "Item" not in response:
            logger.error(f"[handler] Approval ID not found: {approval_id}")
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Approval request not found or expired"})
            }

        approval_item = response["Item"]
        logger.info(f"[handler] Retrieved approval request: {approval_id}")
    except ClientError as e:
        logger.error(f"[handler] Failed to retrieve approval from DynamoDB: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Failed to retrieve approval request"})
        }

    # Check if already processed
    if approval_item.get("status") != "PENDING":
        logger.warning(f"[handler] Approval already processed: {approval_id}, status: {approval_item.get('status')}")
        return {
            "statusCode": 409,
            "body": json.dumps({
                "error": "Approval request already processed",
                "status": approval_item.get("status")
            })
        }

    task_token = approval_item.get("task_token")
    contract_id = approval_item.get("contract_id")

    if not task_token:
        logger.error(f"[handler] Missing task_token in approval item: {approval_id}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Invalid approval request (missing task_token)"})
        }

    # Prepare callback result
    timestamp = datetime.utcnow().isoformat()
    callback_result = {
        "decision": decision,
        "timestamp": timestamp,
        "comments": comments
    }

    if decision == "APPROVED":
        callback_result["approved_by"] = approver
    else:
        callback_result["rejected_by"] = approver

    # Send result back to Step Functions
    try:
        if decision == "APPROVED":
            step_functions.send_task_success(
                taskToken=task_token,
                output=json.dumps(callback_result)
            )
            logger.info(f"[handler] Sent APPROVED decision to Step Functions for contract {contract_id}")
        else:
            step_functions.send_task_success(
                taskToken=task_token,
                output=json.dumps(callback_result)
            )
            logger.info(f"[handler] Sent REJECTED decision to Step Functions for contract {contract_id}")

        # Update DynamoDB item
        table.update_item(
            Key={"approval_id": approval_id},
            UpdateExpression="SET #status = :status, decision = :decision, approver = :approver, processed_at = :timestamp, comments = :comments",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": decision,
                ":decision": decision,
                ":approver": approver,
                ":timestamp": timestamp,
                ":comments": comments
            }
        )
        logger.info(f"[handler] Updated approval status in DynamoDB: {approval_id}")

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "text/html"
            },
            "body": f"""
            <html>
            <head><title>Contract {decision}</title></head>
            <body style="font-family: Arial, sans-serif; padding: 40px; text-align: center;">
                <h1 style="color: {'green' if decision == 'APPROVED' else 'red'};">
                    Contract {decision}
                </h1>
                <p><strong>Contract ID:</strong> {contract_id}</p>
                <p><strong>Decision:</strong> {decision}</p>
                <p><strong>By:</strong> {approver}</p>
                <p><strong>Timestamp:</strong> {timestamp}</p>
                {f'<p><strong>Comments:</strong> {comments}</p>' if comments else ''}
                <hr>
                <p>The workflow has been notified and will proceed accordingly.</p>
            </body>
            </html>
            """
        }

    except ClientError as e:
        logger.error(f"[handler] Failed to send callback to Step Functions: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Failed to process approval decision",
                "details": str(e)
            })
        }

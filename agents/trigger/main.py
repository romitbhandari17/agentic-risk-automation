import os
import json
import uuid
import logging
from typing import Any, Dict

import boto3

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:968239734180:stateMachine:agentic-risk-automation-dev-contract-review")

step_functions = boto3.client("stepfunctions", region_name=AWS_REGION)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Trigger Lambda for initiating Step Functions workflow using the callback/task-token pattern.

    This function will START the execution and return immediately. The state machine should
    include a Task that passes a task token to a worker (ingestion/risk agents). Those workers
    must call Step Functions `send_task_success` / `send_task_failure` (or the appropriate SDK)
    with the received task token to resume/complete the execution.

    Input (direct invocation):
    {
      "s3": {"bucket": "my-bucket", "key": "contracts/contract.pdf"},
      "vendor_metadata": {"region": "us-east-1", "contract_type": "MSA"},
      "contract_id": "..."  # optional
    }
    """

    # Normalize/generate contract ID
    contract_id = event.get("contract_id") or str(uuid.uuid4())

    # Build input for the state machine
    sfn_input = {
        "s3": {
            "bucket": event.get("s3", {}).get("bucket"),
            "key": event.get("s3", {}).get("key")
        },
        "vendor_metadata": event.get("vendor_metadata"),
        "contract_id": contract_id
    }

    print("sfn_input:", json.dumps(sfn_input, indent=2))

    execution_name = f"contract-{contract_id}-{uuid.uuid4().hex[:8]}"

    try:
        response = step_functions.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=execution_name,
            input=json.dumps(sfn_input)
        )

        execution_arn = response.get("executionArn")
        start_date = None
        if response.get("startDate"):
            # StartDate in boto3 is a datetime; convert to ISO string for JSON
            start_date = response["startDate"].isoformat()

        logger.info(f"[handler] Started Step Functions execution: {execution_name}")
        logger.info(f"[handler] Execution ARN: {execution_arn}")

        print(f"[handler] Started execution: {execution_arn}")

        # Return immediately with execution details — downstream workers should callback using task tokens
        result_payload = {
            "message": "Execution started; awaiting callback from workers",
            "execution_arn": execution_arn,
            "execution_name": execution_name,
            "contract_id": contract_id,
            "start_date": start_date,
            "status": "STARTED"
        }

        return {"statusCode": 202, **result_payload}

    except Exception as e:
        logger.error(f"[handler] Failed to start Step Functions execution: {e}")
        error_payload = {"error": "Failed to start workflow", "details": str(e), "contract_id": contract_id}
        return {"statusCode": 500, **error_payload}


if __name__ == "__main__":
    # Local test event
    test_event = {
        "s3": {
            "bucket": "agentic-risk-automation-dev-artifacts",
            "key": "contracts/contract.pdf"
        },
        "vendor_metadata": {
            "region": "us-east-1",
            "contract_type": "MSA"
        }
    }

    result = handler(test_event, None)
    print(json.dumps(result, indent=2))

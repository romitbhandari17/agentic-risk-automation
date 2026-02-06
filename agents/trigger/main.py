import os
import json
import uuid
import logging
from importlib.metadata import metadata
from typing import Any, Dict
import time
from datetime import datetime, timezone

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
    Trigger Lambda for initiating Step Functions workflow.

    Can be invoked by:
    1. S3 Event Notification
    2. EventBridge Rule
    3. Direct Lambda invocation
    4. API Gateway

    Input formats:

    # Direct invocation:
    {
      "s3": {
        "bucket": "my-bucket",
        "key": "contracts/contract.pdf"
      },
      "vendor_metadata": {
        "region": "us-east-1",
        "contract_type": "MSA"
      }
    }

    # S3 Event Notification:
    {
      "Records": [{
        "s3": {
          "bucket": {"name": "..."},
          "object": {"key": "..."}
        }
      }]
    }
    """

    bucket=""
    key=""
    metadata=""
    contract_id=""
    logger.info(f"event: %s", json.dumps(event, indent=2))

    if "Records" in event and event["Records"]:
        rec = event["Records"][0]
        try:
            bucket = rec["s3"]["bucket"]["name"]
            key = rec["s3"]["object"]["key"]
            metadata =  rec.get("vendor_metadata") or ""
            contract_id = rec.get("contract_id") or str(uuid.uuid4())
            logger.info(f"S3 event - bucket=%s key=%s", bucket, key)
        except KeyError:
            logger.info("S3 record missing expected fields: %s", json.dumps(rec))
    else:
        s3 = event["s3"]
        logger.info("S3 event - bucket=%s key=%s metadata=%s", s3.get("bucket"), s3.get("key"), event.get("vendor_metadata"))
        bucket = s3.get("bucket")
        key = s3.get("key")
        metadata = event.get("vendor_metadata") or ""
        contract_id = event.get("contract_id") or str(uuid.uuid4())


    # Prepare Step Functions input
    sfn_input = {
        "s3": {
            "bucket": bucket,
            "key": key
        },
        "vendor_metadata": metadata,
        "contract_id": contract_id
    }

    # sfn_input = {
    #     "s3": {
    #         "bucket": "agentic-risk-automation-dev-artifacts",
    #         "key": "contracts/contract.pdf"
    #     },
    #     "vendor_metadata": {
    #         "region": "us-east-1",
    #         "contract_type": "MSA"
    #     }
    # }

    print("sfn_input: %s", json.dumps(sfn_input, indent=2))
    logger.info(f"sfn_input: %s", json.dumps(sfn_input, indent=2))

    # Start Step Functions execution and poll for completion (up to 5 minutes)
    execution_name = f"contract-{contract_id}-{uuid.uuid4().hex[:8]}"

    try:
        response = step_functions.start_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            name=execution_name,
            input=json.dumps(sfn_input)
        )

        execution_arn = response["executionArn"]
        start_date = response["startDate"].isoformat()

        logger.info(f"[handler] Started Step Functions execution: {execution_name}")
        logger.info(f"[handler] Execution ARN: {execution_arn}")

        print(f"[handler] Started execution: {execution_arn}")

        # Poll for status until terminal or timeout
        timeout_seconds = 300  # 5 minutes
        poll_interval = 2
        start_ts = time.time()

        while True:
            try:
                desc = step_functions.describe_execution(executionArn=execution_arn)
            except Exception as e:
                print(f"[handler] Error describing execution: {e}")
                logger.exception("Error describing execution")
                return {
                    "statusCode": 500,
                    "error": "Failed to describe execution",
                    "details": str(e),
                    "contract_id": contract_id
                }

            status = desc.get("status")
            print(f"[handler] Execution status: {status}")

            if status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
                output = desc.get("output")
                parsed_output = None
                if output:
                    try:
                        parsed_output = json.loads(output)
                    except Exception:
                        parsed_output = output

                print("[handler] Execution finished. Status:", status)
                print("[handler] Execution output:")

                if status == "SUCCEEDED":
                    result_payload = {
                        "message": "Contract review workflow succeeded",
                        "execution_arn": execution_arn,
                        "execution_name": execution_name,
                        "contract_id": contract_id,
                        "start_date": start_date,
                        "status": status,
                        "output": parsed_output
                    }

                    return {
                        "statusCode": 200,
                        **result_payload
                    }
                else:
                    # FAILED / TIMED_OUT / ABORTED
                    result_payload = {
                        "message": "Contract review workflow finished with error",
                        "execution_arn": execution_arn,
                        "execution_name": execution_name,
                        "contract_id": contract_id,
                        "start_date": start_date,
                        "status": status,
                        "output": parsed_output
                    }

                    return {
                        "statusCode": 500,
                        **result_payload
                    }

            # not terminal yet
            elapsed = time.time() - start_ts
            if elapsed > timeout_seconds:
                print("[handler] Execution timed out after 5 minutes")
                return {
                    "statusCode": 504,
                    "error": "Execution timed out",
                    "contract_id": contract_id
                }

            time.sleep(poll_interval)

    except Exception as e:
        logger.error(f"[handler] Failed to start Step Functions execution: {e}")

        error_payload = {
            "error": "Failed to start workflow",
            "details": str(e),
            "contract_id": contract_id
        }

        return {
            "statusCode": 500,
            **error_payload
        }



# if __name__ == "__main__":
#     # Local test event
#     test_event = {
#         "s3": {
#             "bucket": "agentic-risk-automation-dev-artifacts",
#             "key": "contracts/contract.pdf"
#         },
#         "vendor_metadata": {
#             "region": "us-east-1",
#             "contract_type": "MSA"
#         }
#     }
#
#     result = handler(test_event, None)
#     print(json.dumps(result, indent=2))

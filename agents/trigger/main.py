import os
import json
import uuid
import logging
from typing import Any, Dict

import boto3

# Also import local ingestion and risk handlers so trigger can call them directly when running locally
try:
    from agents.ingestion import main as ingestion_main
except Exception:
    ingestion_main = None

try:
    from agents.risk_analysis import main as risk_main
except Exception:
    risk_main = None

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

    # For local development default event (can be overridden by incoming event)
    event = event or {
        "s3": {
            "bucket": "agentic-risk-automation-dev-artifacts",
            "key": "contracts/contract.pdf"
        },
        "vendor_metadata": {
            "region": "us-east-1",
            "contract_type": "MSA"
        }
    }

    logger.info(f"[handler] Trigger Lambda invoked with event keys: {list(event.keys())}")

    # Parse S3 event
    if "Records" in event and event["Records"]:
        # S3 event notification format
        record = event["Records"][0]
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        vendor_metadata = {
            "region": "us-east-1",
            "contract_type": "MSA",
            "source": "s3-event"
        }

        logger.info(f"[handler] Parsed S3 event: s3://{bucket}/{key}")
    elif "s3" in event:
        # Direct format
        s3_field = event["s3"]
        # allow either dict with bucket/key or direct values
        if isinstance(s3_field, dict) and "bucket" in s3_field and "key" in s3_field:
            bucket = s3_field["bucket"]
            key = s3_field["key"]
        else:
            # assume legacy flat structure
            bucket = event["s3"].get("bucket") if isinstance(event["s3"], dict) else event["s3"]
            key = event["s3"].get("key") if isinstance(event["s3"], dict) else None

        vendor_metadata = event.get("vendor_metadata", {
            "region": "us-east-1",
            "contract_type": "MSA"
        })

        logger.info(f"[handler] Parsed direct invocation: s3://{bucket}/{key}")
    else:
        error_msg = "Invalid event format. Expected S3 event or direct format with 's3' key"
        logger.error(f"[handler] {error_msg}")
        raise ValueError(error_msg)

    # Generate contract ID if not provided
    contract_id = event.get("contract_id") or str(uuid.uuid4())

    # Prepare Step Functions input
    sfn_input = {
        "s3": {
            "bucket": bucket,
            "key": key
        },
        "vendor_metadata": vendor_metadata,
        "contract_id": contract_id
    }

    # Call ingestion handler locally (when available) to get extracted clauses and contract_id
    ingestion_result = None
    if ingestion_main and hasattr(ingestion_main, "handler"):
        try:
            logger.info("[handler] Invoking local ingestion handler")
            ingestion_result = ingestion_main.handler(sfn_input, None)
            logger.info(f"[handler] Ingestion returned keys: {list(ingestion_result.keys()) if isinstance(ingestion_result, dict) else 'N/A'}")
            # prefer contract_id returned by ingestion if present
            contract_id = ingestion_result.get("contract_id") or contract_id
            extracted = ingestion_result.get("extracted") if isinstance(ingestion_result, dict) else None
        except Exception as e:
            logger.exception("[handler] Local ingestion handler failed")
            ingestion_result = {"status": "error", "reason": str(e), "contract_id": contract_id}
            extracted = None
    else:
        logger.info("[handler] Local ingestion handler not available; skipping local ingestion call")
        extracted = None

    # Now call risk analysis handler locally using ingestion result
    risk_result = None
    if risk_main and hasattr(risk_main, "handler") and isinstance(ingestion_result, dict) and ingestion_result.get("status") == "INGESTED":
        try:
            logger.info("[handler] Invoking local risk analysis handler with ingestion output")
            risk_event = {
                "contract_id": contract_id,
                "extracted": ingestion_result.get("extracted"),
                "s3": sfn_input.get("s3"),
                "vendor_metadata": vendor_metadata
            }
            risk_result = risk_main.handler(risk_event, None)
            logger.info(f"[handler] Risk analysis returned keys: {list(risk_result.keys()) if isinstance(risk_result, dict) else 'N/A'}")
        except Exception as e:
            logger.exception("[handler] Local risk analysis handler failed")
            risk_result = {"status": "error", "reason": str(e), "contract_id": contract_id}
    else:
        logger.info("[handler] Local risk analysis handler not available or ingestion failed; skipping local risk call")

    # Start Step Functions execution
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

        # Build a response object that includes contract_id and any ingestion/risk outputs
        result_payload = {
            "message": "Contract review workflow started",
            "execution_arn": execution_arn,
            "execution_name": execution_name,
            "contract_id": contract_id,
            "start_date": start_date,
            "s3_location": f"s3://{bucket}/{key}",
            "ingestion_result": ingestion_result,
            "risk_result": risk_result
        }

        return {
            "statusCode": 200,
            "body": json.dumps(result_payload),
            **result_payload
        }

    except Exception as e:
        logger.error(f"[handler] Failed to start Step Functions execution: {e}")

        error_payload = {
            "error": "Failed to start workflow",
            "details": str(e),
            "contract_id": contract_id,
            "ingestion_result": ingestion_result,
            "risk_result": risk_result
        }

        return {
            "statusCode": 500,
            "body": json.dumps(error_payload),
            **error_payload
        }



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

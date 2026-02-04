from agents.ingestion.main import handler
import uuid

# Local test trigger: include contract_id so ingestion sees it in the request
event = {
    "s3": {"bucket": "agentic-risk-automation-dev-artifacts", "key": "contracts/contract.pdf"},
    "vendor_metadata": {"region": "us-east-1", "contract_type": "MSA"},
    "contract_id": str(uuid.uuid4())
}

print(handler(event, None))
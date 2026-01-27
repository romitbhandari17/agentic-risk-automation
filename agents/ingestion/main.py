import json
from typing import Any, Dict

# Simple ingestion Lambda handler stub

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Receive raw data, validate minimal shape, and return ingestion result.

    Args:
        event: Lambda event payload
        context: Lambda context

    Returns:
        dict: result object
    """
    # Example: expect event to contain "document" with text
    document = event.get("document")
    if not document:
        return {"status": "error", "reason": "missing document"}

    # In a real agent, you'd validate, enrich, and store the document here.
    return {"status": "ok", "ingested_length": len(document)}

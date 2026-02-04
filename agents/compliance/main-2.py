import os
import json
import time
import uuid
import logging
from typing import Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# -------- Config (env vars) --------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
DDB_TABLE = os.environ.get("DDB_TABLE", "contract_risk_analysis")  # e.g., "contracts-structured"
# MODEL_ID can be a base model ID or an inference profile ID/ARN.
# For Amazon Nova, it's recommended to use cross-region inference profiles for better availability/throughput.
# e.g., "us.amazon.nova-lite-v1:0" for cross-region inference profile.
MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-lite-v1:0")
MAX_CHARS_PER_CHUNK = int(os.environ.get("MAX_CHARS_PER_CHUNK", "12000"))
BEDROCK_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "1200"))

s3 = boto3.client("s3", region_name=AWS_REGION)
textract = boto3.client("textract", region_name=AWS_REGION)
bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
# ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
# table = ddb.Table(DDB_TABLE)

# -------- Schema for strict extraction --------
EXTRACTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "governing_law": {"type": ["string", "null"]},
        "termination_clause": {"type": ["string", "null"]},
        "liability_clause": {"type": ["string", "null"]},
        "indemnity_clause": {"type": ["string", "null"]},
        "data_protection": {"type": ["string", "null"]},
        "payment_terms": {"type": ["string", "null"]},
        "renewal_terms": {"type": ["string", "null"]},
    },
    "required": [
        "governing_law",
        "termination_clause",
        "liability_clause",
        "indemnity_clause",
        "data_protection",
        "payment_terms",
        "renewal_terms",
    ],
}

FIELDS = [
    "governing_law",
    "termination_clause",
    "liability_clause",
    "indemnity_clause",
    "data_protection",
    "payment_terms",
    "renewal_terms",
]


# -------- Helpers --------
def _json_loads_safely(text: str) -> Dict[str, Any]:
    """
    Attempts to parse a JSON object from a model response that may include extra text.
    We extract the first {...} block as a pragmatic guardrail.
    """
    logger.info("_json_loads_safely: Starting JSON parsing")
    logger.debug(f"_json_loads_safely: Input text length: {len(text)}")

    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        logger.info("_json_loads_safely: Text is valid JSON format, parsing")
        result = json.loads(text)
        logger.info("_json_loads_safely: Successfully parsed JSON")
        return result

    logger.info("_json_loads_safely: Extracting JSON block from text")
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        logger.info(f"_json_loads_safely: Found JSON block from position {start} to {end}")
        result = json.loads(text[start : end + 1])
        logger.info("_json_loads_safely: Successfully parsed extracted JSON")
        return result

    logger.error("_json_loads_safely: No JSON object found in model output")
    raise ValueError("No JSON object found in model output")


def _validate_schema_minimal(obj: Dict[str, Any]) -> None:
    # Minimal validation without external dependency:
    logger.info("_validate_schema_minimal: Starting schema validation")

    if not isinstance(obj, dict):
        logger.error("_validate_schema_minimal: Extraction output is not an object")
        raise ValueError("Extraction output is not an object")

    extra = set(obj.keys()) - set(FIELDS)
    if extra:
        logger.error(f"_validate_schema_minimal: Unexpected fields found: {sorted(extra)}")
        raise ValueError(f"Unexpected fields in output: {sorted(extra)}")

    missing = [k for k in FIELDS if k not in obj]
    if missing:
        logger.error(f"_validate_schema_minimal: Missing required fields: {missing}")
        raise ValueError(f"Missing required fields: {missing}")

    for k in FIELDS:
        v = obj.get(k)
        if v is not None and not isinstance(v, str):
            logger.error(f"_validate_schema_minimal: Field '{k}' has invalid type: {type(v)}")
            raise ValueError(f"Field '{k}' must be string or null")

    logger.info("_validate_schema_minimal: Schema validation passed")


def _chunk_text(text: str, max_chars: int) -> List[str]:
    logger.info(f"_chunk_text: Starting text chunking with max_chars={max_chars}")
    logger.info(f"_chunk_text: Input text length: {len(text)} characters")

    text = " ".join(text.split())  # normalize whitespace
    logger.debug(f"_chunk_text: After normalization, text length: {len(text)}")

    if len(text) <= max_chars:
        logger.info("_chunk_text: Text fits in single chunk, no splitting needed")
        return [text]

    logger.info("_chunk_text: Text requires chunking, processing...")
    chunks: List[str] = []
    i = 0
    while i < len(text):
        j = min(i + max_chars, len(text))
        # try to cut on a boundary
        cut = text.rfind(". ", i, j)
        if cut == -1 or cut <= i + int(max_chars * 0.6):
            cut = text.rfind(" ", i, j)
        if cut == -1 or cut <= i:
            cut = j
        chunks.append(text[i:cut].strip())
        logger.debug(f"_chunk_text: Created chunk {len(chunks)} with {cut - i} characters")
        i = cut

    filtered_chunks = [c for c in chunks if c]
    logger.info(f"_chunk_text: Completed chunking. Total chunks created: {len(filtered_chunks)}")
    return filtered_chunks


def _build_prompt(contract_text_chunk: str, vendor_metadata: Dict[str, Any]) -> str:
    logger.info("_build_prompt: Building prompt for Bedrock")
    logger.debug(f"_build_prompt: Chunk length: {len(contract_text_chunk)}, Metadata keys: {list(vendor_metadata.keys())}")

    prompt = f"""You are a contract ingestion agent.
Extract the following fields ONLY in JSON (no commentary, no markdown, no code fences):
- governing_law
- termination_clause
- liability_clause
- indemnity_clause
- data_protection
- payment_terms
- renewal_terms

If a field is missing, return null.
Do not invent facts. Use only the provided text.

Vendor metadata (may help interpret the contract, but do not override text):
{json.dumps(vendor_metadata, ensure_ascii=False)}

Contract text:
\"\"\"{contract_text_chunk}\"\"\"
"""
    logger.info(f"_build_prompt: Prompt built successfully, length: {len(prompt)}")
    return prompt


def _invoke_bedrock(prompt: str) -> Dict[str, Any]:
    """
    Invokes Bedrock model. Supports Anthropic Claude and Amazon Nova model families.
    """
    logger.info(f"_invoke_bedrock: Invoking Bedrock model: {MODEL_ID}")
    logger.debug(f"_invoke_bedrock: Prompt length: {len(prompt)}, Max tokens: {BEDROCK_MAX_TOKENS}")

    if MODEL_ID.startswith("anthropic."):
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": BEDROCK_MAX_TOKENS,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
        }
    elif MODEL_ID.startswith("amazon.nova-") or "nova" in MODEL_ID.lower():
        body = {
            "inferenceConfig": {
                "maxTokens": BEDROCK_MAX_TOKENS,
                "temperature": 0,
            },
            "messages": [
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
        }
    else:
        # Fallback/default to Anthropic format
        logger.warning(f"_invoke_bedrock: Unrecognized model family for {MODEL_ID}, attempting Anthropic format")
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": BEDROCK_MAX_TOKENS,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
        }

    logger.info("_invoke_bedrock: Sending request to Bedrock")

    resp = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body).encode("utf-8"),
        accept="application/json",
        contentType="application/json",
    )
    logger.info("_invoke_bedrock: Received response from Bedrock")

    payload = json.loads(resp["body"].read().decode("utf-8"))
    logger.debug(f"_invoke_bedrock: Response payload keys: {list(payload.keys())}")

    # Extract text based on model family
    if MODEL_ID.startswith("anthropic."):
        # Claude responses usually look like: {"content":[{"type":"text","text":"..."}], ...}
        content = payload.get("content", [])
        text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
        model_text = "\n".join(text_parts).strip()
    elif MODEL_ID.startswith("amazon.nova-") or "nova" in MODEL_ID.lower():
        # Nova responses: {"output": {"message": {"content": [{"text": "..."}]}}}
        output = payload.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])
        text_parts = [p.get("text", "") for p in content if "text" in p]
        model_text = "\n".join(text_parts).strip()
    else:
        # Generic fallback
        content = payload.get("content", [])
        if isinstance(content, list) and content and isinstance(content[0], dict):
             text_parts = [p.get("text", "") for p in content if "text" in p]
             model_text = "\n".join(text_parts).strip()
        else:
             model_text = str(payload)

    logger.info(f"_invoke_bedrock: Extracted model text, length: {len(model_text)}")

    extracted = _json_loads_safely(model_text)
    extracted = _coerce_extraction_types(extracted)
    logger.info("_invoke_bedrock: JSON extraction successful")

    _validate_schema_minimal(extracted)
    logger.info("_invoke_bedrock: Schema validation passed, returning extracted data")
    return extracted


def _coerce_extraction_types(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Coerce only expected fields; unexpected fields are left as-is so validation can still reject them.
    """
    logger.info("_coerce_extraction_types: Coercing extraction field types (if needed)")
    for k in FIELDS:
        if k in obj:
            obj[k] = _coerce_value_to_string_or_none(k, obj.get(k))
    return obj


def _coerce_value_to_string_or_none(field_name: str, value: Any) -> Optional[str]:
    """
    Bedrock models sometimes return objects/arrays for a field. Our schema expects:
      - string, or
      - null
    This function coerces:
      - dict -> compact JSON string
      - list/tuple -> join items into a string (JSON for dict items)
      - numbers/bools -> string
      - empty/whitespace -> None
    """
    if value is None:
        return None

    if isinstance(value, str):
        v = value.strip()
        return v if v else None

    if isinstance(value, dict):
        logger.info(f"_coerce_value_to_string_or_none: Coercing dict -> string for field '{field_name}'")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    if isinstance(value, (list, tuple)):
        logger.info(f"_coerce_value_to_string_or_none: Coercing list/tuple -> string for field '{field_name}'")
        parts: List[str] = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                s = item.strip()
                if s:
                    parts.append(s)
            elif isinstance(item, dict):
                parts.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            else:
                parts.append(str(item))
        joined = "\n".join(parts).strip()
        return joined if joined else None

    logger.info(f"_coerce_value_to_string_or_none: Coercing {type(value).__name__} -> string for field '{field_name}'")
    s = str(value).strip()
    return s if s else None


def _merge_extractions(extractions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Prefer first non-null value across chunks.
    For long clauses, you might prefer concatenation; here we take first hit.
    """
    logger.info(f"_merge_extractions: Merging {len(extractions)} extraction results")

    merged: Dict[str, Any] = {k: None for k in FIELDS}
    for idx, ext in enumerate(extractions):
        logger.debug(f"_merge_extractions: Processing extraction {idx + 1}/{len(extractions)}")
        for k in FIELDS:
            if merged[k] is None and ext.get(k) is not None:
                logger.debug(f"_merge_extractions: Found value for field '{k}' in extraction {idx + 1}")
                merged[k] = ext.get(k)

    filled_fields = sum(1 for v in merged.values() if v is not None)
    logger.info(f"_merge_extractions: Merge complete. {filled_fields}/{len(FIELDS)} fields populated")
    return merged


# -------- Textract (PDF/DOCX) via asynchronous job --------
def _start_textract_job(bucket: str, key: str) -> str:
    logger.info(f"_start_textract_job: Starting Textract job for s3://{bucket}/{key}")

    resp = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
    )
    job_id = resp["JobId"]
    logger.info(f"_start_textract_job: Textract job started successfully with JobId: {job_id}")
    return job_id


def _wait_for_textract(job_id: str, timeout_seconds: int = 180) -> None:
    logger.info(f"_wait_for_textract: Waiting for Textract job {job_id} (timeout: {timeout_seconds}s)")

    start = time.time()
    poll_count = 0
    while True:
        poll_count += 1
        resp = textract.get_document_text_detection(JobId=job_id, MaxResults=1)
        status = resp["JobStatus"]
        elapsed = time.time() - start

        logger.debug(f"_wait_for_textract: Poll #{poll_count}, Status: {status}, Elapsed: {elapsed:.1f}s")

        if status in ("SUCCEEDED", "FAILED", "PARTIAL_SUCCESS"):
            if status != "SUCCEEDED":
                logger.error(f"_wait_for_textract: Textract job ended with status={status}")
                raise RuntimeError(f"Textract job ended with status={status}")
            logger.info(f"_wait_for_textract: Textract job succeeded after {elapsed:.1f}s ({poll_count} polls)")
            return

        if time.time() - start > timeout_seconds:
            logger.error(f"_wait_for_textract: Timeout after {timeout_seconds}s waiting for job {job_id}")
            raise TimeoutError("Timed out waiting for Textract job")

        time.sleep(2)


def _get_textract_text(job_id: str) -> str:
    logger.info(f"_get_textract_text: Retrieving text from Textract job {job_id}")

    blocks: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    page_count = 0

    while True:
        page_count += 1
        kwargs = {"JobId": job_id, "MaxResults": 1000}
        if next_token:
            kwargs["NextToken"] = next_token

        logger.debug(f"_get_textract_text: Fetching page {page_count} of results")
        resp = textract.get_document_text_detection(**kwargs)
        blocks.extend(resp.get("Blocks", []))
        next_token = resp.get("NextToken")

        logger.debug(f"_get_textract_text: Page {page_count} returned {len(resp.get('Blocks', []))} blocks")

        if not next_token:
            logger.info(f"_get_textract_text: Retrieved all {page_count} pages, total blocks: {len(blocks)}")
            break

    # Collect LINE text in reading-ish order as returned
    lines = [b["Text"] for b in blocks if b.get("BlockType") == "LINE" and "Text" in b]
    logger.info(f"_get_textract_text: Extracted {len(lines)} lines of text")

    text = "\n".join(lines).strip()
    logger.info(f"_get_textract_text: Final text length: {len(text)} characters")
    return text


# -------- DynamoDB persistence --------
# def _put_to_ddb(
#         contract_id: str,
#         s3_bucket: str,
#         s3_key: str,
#         vendor_metadata: Dict[str, Any],
#         extracted: Dict[str, Any],
# ) -> None:
#     now = int(time.time())
#     item = {
#         "contract_id": contract_id,
#         "source_s3_bucket": s3_bucket,
#         "source_s3_key": s3_key,
#         "vendor_metadata": vendor_metadata,
#         "extracted": extracted,
#         "created_at": now,
#         "updated_at": now,
#         "status": "INGESTED",
#     }
#     table.put_item(Item=item)


# -------- Lambda handler --------
def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Expected event shape (example):
    {
      "s3": {"bucket": "my-bucket", "key": "contracts/acme.pdf"},
      "vendor_metadata": {"region":"NA","contract_type":"MSA"},
      "contract_id": "optional-existing-id"
    }

    If invoked directly from S3 EventBridge/S3 notification, you can adapt parsing below.
    """
    logger.info("=" * 80)
    logger.info("handler: Lambda invocation started")
    logger.info(f"handler: Event keys: {list(event.keys())}")

    # --- Parse inputs ---
    if "s3" in event:
        logger.info("handler: Parsing event in direct S3 format")
        bucket = event["s3"]["bucket"]
        key = event["s3"]["key"]
        vendor_metadata = event.get("vendor_metadata", {})
        contract_id = event.get("contract_id") or str(uuid.uuid4())
    elif "Records" in event and event["Records"] and "s3" in event["Records"][0]:
        logger.info("handler: Parsing event in S3 notification format")
        # S3 notification format
        rec = event["Records"][0]
        bucket = rec["s3"]["bucket"]["name"]
        key = rec["s3"]["object"]["key"]
        vendor_metadata = event.get("vendor_metadata", {})
        contract_id = event.get("contract_id") or str(uuid.uuid4())
    else:
        logger.error("handler: Unsupported event format")
        raise ValueError("Unsupported event format. Provide 's3' or S3 notification 'Records'.")

    logger.info(f"handler: Contract ID: {contract_id}")
    logger.info(f"handler: S3 Location: s3://{bucket}/{key}")
    logger.info(f"handler: Vendor metadata: {vendor_metadata}")

    # --- Textract OCR ---
    logger.info("handler: Starting Textract OCR phase")
    job_id = _start_textract_job(bucket, key)
    _wait_for_textract(job_id)
    full_text = _get_textract_text(job_id)

    if not full_text:
        logger.error("handler: Textract returned empty text")
        raise RuntimeError("Textract returned empty text")

    logger.info("handler: Textract OCR phase completed successfully")

    # --- Chunking + Bedrock extraction ---
    logger.info("handler: Starting chunking and Bedrock extraction phase")
    chunks = _chunk_text(full_text, MAX_CHARS_PER_CHUNK)
    extractions: List[Dict[str, Any]] = []
    errors: List[str] = []

    logger.info(f"handler: Processing {len(chunks)} chunks with Bedrock")
    for idx, chunk in enumerate(chunks):
        logger.info(f"handler: Processing chunk {idx + 1}/{len(chunks)}")
        prompt = _build_prompt(chunk, vendor_metadata)
        try:
            extractions.append(_invoke_bedrock(prompt))
            logger.info(f"handler: Successfully processed chunk {idx + 1}/{len(chunks)}")
        except Exception as e:
            error_msg = f"chunk[{idx}]: {type(e).__name__}: {str(e)}"
            logger.error(f"handler: Failed to process chunk {idx + 1}: {error_msg}")
            errors.append(error_msg)

    if not extractions:
        logger.error(f"handler: All Bedrock extractions failed. Errors: {errors[:3]}")
        raise RuntimeError(f"All Bedrock extractions failed. Errors: {errors[:3]}")

    logger.info(f"handler: Successfully extracted data from {len(extractions)}/{len(chunks)} chunks")

    # --- Merge and validate ---
    logger.info("handler: Merging extraction results")
    merged = _merge_extractions(extractions)
    _validate_schema_minimal(merged)
    logger.info("handler: Merge and validation completed successfully")

    # --- Store in DynamoDB ---
    # _put_to_ddb(contract_id, bucket, key, vendor_metadata, merged)

    logger.info("handler: Preparing final response")
    response = {
        "contract_id": contract_id,
        "source": {"bucket": bucket, "key": key},
        "extracted": merged,
        "chunk_count": len(chunks),
        "bedrock_failures": errors,  # keep for audit/debug; you can omit in production response
        "status": "INGESTED",
    }

    logger.info(f"handler: Lambda execution completed successfully. Status: {response['status']}")
    logger.info("=" * 80)
    return response
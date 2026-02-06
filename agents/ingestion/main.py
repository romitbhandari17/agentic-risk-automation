import os
import json
import time
import uuid
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# -------- Config (env vars) --------
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
# MODEL_ID can be a base model ID or an inference profile ID/ARN.
# For Amazon Nova, it's recommended to use cross-region inference profiles for better availability/throughput.
# e.g., "us.amazon.nova-lite-v1:0" for cross-region inference profile.
MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-lite-v1:0")
MAX_CHARS_PER_CHUNK = int(os.environ.get("MAX_CHARS_PER_CHUNK", "12000"))
BEDROCK_MAX_TOKENS = int(os.environ.get("BEDROCK_MAX_TOKENS", "1200"))

# Add configurable Textract wait timeout
TEXTRACT_WAIT_TIMEOUT = int(os.environ.get("TEXTRACT_WAIT_TIMEOUT", "300"))  # seconds

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
    print("_json_loads_safely: Starting JSON parsing")
    logger.debug(f"_json_loads_safely: Input text length: {len(text)}")

    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        print("_json_loads_safely: Text is valid JSON format, parsing")
        result = json.loads(text)
        print("_json_loads_safely: Successfully parsed JSON")
        return result

    print("_json_loads_safely: Extracting JSON block from text")
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        print(f"_json_loads_safely: Found JSON block from position {start} to {end}")
        result = json.loads(text[start : end + 1])
        print("_json_loads_safely: Successfully parsed extracted JSON")
        return result

    print("_json_loads_safely: No JSON object found in model output")
    raise ValueError("No JSON object found in model output")


def _validate_schema_minimal(obj: Dict[str, Any]) -> None:
    # Minimal validation without external dependency:
    print("_validate_schema_minimal: Starting schema validation")

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

    print("_validate_schema_minimal: Schema validation passed")


def _chunk_text(text: str, max_chars: int) -> List[str]:
    print(f"_chunk_text: Starting text chunking with max_chars={max_chars}")
    print(f"_chunk_text: Input text length: {len(text)} characters")

    text = " ".join(text.split())  # normalize whitespace
    logger.debug(f"_chunk_text: After normalization, text length: {len(text)}")

    if len(text) <= max_chars:
        print("_chunk_text: Text fits in single chunk, no splitting needed")
        return [text]

    print("_chunk_text: Text requires chunking, processing...")
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
    print(f"_chunk_text: Completed chunking. Total chunks created: {len(filtered_chunks)}")
    return filtered_chunks


def _build_prompt(contract_text_chunk: str, vendor_metadata: Dict[str, Any]) -> str:
    print("_build_prompt: Building prompt for Bedrock")
    logger.debug(f"_build_prompt: Chunk length: {len(contract_text_chunk)}, Metadata: {vendor_metadata}")

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
    print(f"_build_prompt: Prompt built successfully, length: {len(prompt)}")
    return prompt


def _invoke_bedrock(prompt: str) -> Dict[str, Any]:
    """
    Invokes Bedrock model. Supports Anthropic Claude and Amazon Nova model families.
    """
    print(f"_invoke_bedrock: Invoking Bedrock model: {MODEL_ID}")
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

    print("_invoke_bedrock: Sending request to Bedrock")

    resp = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body).encode("utf-8"),
        accept="application/json",
        contentType="application/json",
    )
    print("_invoke_bedrock: Received response from Bedrock")

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

    print(f"_invoke_bedrock: Extracted model text, length: {len(model_text)}")

    extracted = _json_loads_safely(model_text)
    extracted = _coerce_extraction_types(extracted)
    print("_invoke_bedrock: JSON extraction successful")

    _validate_schema_minimal(extracted)
    print("_invoke_bedrock: Schema validation passed, returning extracted data")
    return extracted


def _coerce_extraction_types(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Coerce extraction output values so every field is either a string or None.
    Uses _coerce_value_to_string_or_none to handle dicts/lists/numbers/booleans.
    """
    print("_coerce_extraction_types: Coercing extraction output types using helper")
    coerced: Dict[str, Any] = {}

    for k in FIELDS:
        coerced[k] = _coerce_value_to_string_or_none(k, obj.get(k))

    print("_coerce_extraction_types: Coercion complete")
    return coerced


def get_errors(ddb_item: Dict[str, Any]) -> List[str]:
    logger.info("get_errors: Starting error extraction")
    logger.debug(f"get_errors: Input item: {ddb_item}")

    errors = []

    for field in FIELDS:
        value = ddb_item.get(field)
        logger.debug(f"get_errors: Checking field '{field}', value: {value}")

        if value in (None, "", "null"):
            logger.warning(f"get_errors: Field '{field}' is empty or null")
            errors.append(f"Field '{field}' is empty or null")

    logger.info(f"get_errors: Error extraction completed, found {len(errors)} errors")
    return errors


def _coerce_value_to_string_or_none(field_name: str, value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, str):
        v = value.strip()
        return v if v else None

    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    if isinstance(value, (list, tuple)):
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

    s = str(value).strip()
    return s if s else None


def _merge_extractions(extractions: List[Dict[str, Any]]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {k: None for k in FIELDS}
    for idx, ext in enumerate(extractions):
        for k in FIELDS:
            if merged[k] is None and ext.get(k) is not None:
                merged[k] = ext.get(k)
    return merged


# Textract helpers (async job)
def _start_textract_job(bucket: str, key: str) -> str:
    print(f"_start_textract_job: Starting Textract job for s3://{bucket}/{key}")
    try:
        resp = textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
        )
    except Exception as e:
        print(f"_start_textract_job: Failed to start Textract job: {e}")
        raise

    # Log the response to help diagnostics (JobId and any metadata)
    job_id = resp.get("JobId")
    print(f"_start_textract_job: Textract start response JobId={job_id}, full_resp_keys={list(resp.keys())}")
    return job_id


def _wait_for_textract(job_id: str, timeout_seconds: Optional[int] = None) -> None:
    if timeout_seconds is None:
        timeout_seconds = TEXTRACT_WAIT_TIMEOUT
    print(f"_wait_for_textract: Waiting for Textract job {job_id} (timeout: {timeout_seconds}s)")

    start = time.time()
    last_resp = None
    poll_count = 0
    while True:
        poll_count += 1
        try:
            resp = textract.get_document_text_detection(JobId=job_id, MaxResults=1)
        except Exception as e:
            print(f"_wait_for_textract: Error calling get_document_text_detection: {e}")
            raise

        last_resp = resp
        status = resp.get("JobStatus")
        print(f"_wait_for_textract: Poll #{poll_count}, Status: {status}")

        # If Textract indicates partial success, treat as success but warn
        if status == "SUCCEEDED":
            print(f"_wait_for_textract: Job {job_id} succeeded after {time.time()-start:.1f}s ({poll_count} polls)")
            return
        if status == "PARTIAL_SUCCESS":
            print(f"_wait_for_textract: Job {job_id} completed with PARTIAL_SUCCESS after {time.time()-start:.1f}s ({poll_count} polls)")
            return
        if status == "FAILED":
            # include any returned failure info if present
            failure_info = resp.get("StatusMessage") or resp
            print(f"_wait_for_textract: Textract job failed: {failure_info}")
            raise RuntimeError(f"Textract job ended with status=FAILED: {failure_info}")

        # continue polling
        elapsed = time.time() - start
        if elapsed > timeout_seconds:
            # include last_resp snippet to help diagnose
            snippet = {}
            try:
                snippet = {k: last_resp.get(k) for k in ("JobStatus", "StatusMessage") if last_resp and k in last_resp}
            except Exception:
                snippet = {"note": "could not extract snippet"}
            raise TimeoutError(f"Timed out waiting for Textract job {job_id} after {elapsed:.1f}s; last_resp={snippet}")

        time.sleep(2)


def _get_textract_text(job_id: str) -> str:
    print(f"_get_textract_text: Fetching text for job {job_id}")
    blocks: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    while True:
        kwargs = {"JobId": job_id, "MaxResults": 1000}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = textract.get_document_text_detection(**kwargs)
        blocks.extend(resp.get("Blocks", []))
        next_token = resp.get("NextToken")
        if not next_token:
            break
    lines = [b["Text"] for b in blocks if b.get("BlockType") == "LINE" and "Text" in b]
    text = "\n".join(lines).strip()
    print(f"_get_textract_text: Retrieved {len(lines)} lines, total length {len(text)}")
    return text


# Extend handler to run full pipeline
def handler(event, context):
    print("lambda_handler: Received event")
    print(f"lambda_handler: Event details: {json.dumps(event)}")

    if not isinstance(event, dict):
        raise ValueError("Event must be a dict")

    contract_id = event.get("contract_id") or str(uuid.uuid4())

    # parse s3 as before
    bucket = None
    key = None
    if "s3" in event and isinstance(event["s3"], dict) and "bucket" in event["s3"] and "key" in event["s3"]:
        bucket = event["s3"]["bucket"]
        key = event["s3"]["key"]
        print(f"lambda_handler: Parsed direct s3 shape -> s3://{bucket}/{key}")
    elif "Records" in event and event["Records"] and isinstance(event["Records"], list) and "s3" in event["Records"][0]:
        try:
            rec = event["Records"][0]
            bucket = rec["s3"]["bucket"]["name"]
            key = rec["s3"]["object"]["key"]
            # URL-decode the S3 object key
            key = unquote_plus(key)
            print(f"lambda_handler: Parsed S3 notification -> s3://{bucket}/{key}")
        except Exception as e:
            print(f"lambda_handler: Failed to parse S3 notification: {e}")
            raise
    elif "s3" in event and isinstance(event["s3"], dict) and "bucket" in event["s3"] and isinstance(event["s3"]["bucket"], dict) and "name" in event["s3"]["bucket"]:
        bucket = event["s3"]["bucket"]["name"]
        key = event["s3"].get("key") or (event["s3"].get("object") or {}).get("key")
        print(f"lambda_handler: Parsed nested s3 shape -> s3://{bucket}/{key}")
    else:
        raise ValueError("Unsupported event format: expected 's3' or 'Records' with S3 notification")

    # --- Textract OCR ---
    try:
        job_id = _start_textract_job(bucket, key)
        _wait_for_textract(job_id)
        full_text = _get_textract_text(job_id)
        if not full_text:
            err = "Textract returned empty text"
            print(err)
            return {"status": "error", "reason": err, "contract_id": contract_id}
    except Exception as e:
        print(f"Error during Textract: {e}")
        return {"status": "error", "reason": str(e), "contract_id": contract_id}

    # --- Chunking + Bedrock extraction ---
    chunks = _chunk_text(full_text, MAX_CHARS_PER_CHUNK)
    extractions: List[Dict[str, Any]] = []
    errors: List[str] = []

    for idx, chunk in enumerate(chunks):
        prompt = _build_prompt(chunk, event.get("vendor_metadata", {}))
        try:
            extra = _invoke_bedrock(prompt)
            extractions.append(extra)
        except Exception as e:
            errors.append(f"chunk[{idx}]: {type(e).__name__}: {str(e)}")

    if not extractions:
        err = f"All Bedrock extractions failed. Errors: {errors[:3]}"
        print(err)
        return {"status": "error", "reason": err, "contract_id": contract_id}

    merged = _merge_extractions(extractions)
    try:
        _validate_schema_minimal(merged)
    except Exception as e:
        print(f"Validation failed: {e}")
        return {"status": "error", "reason": str(e), "contract_id": contract_id}

    response = {
        "contract_id": contract_id,
        "source": {"bucket": bucket, "key": key},
        "extracted": merged,
        "chunk_count": len(chunks),
        "bedrock_failures": errors,
        "status": "INGESTED",
    }

    print(f"lambda_handler: Completed ingestion for contract_id={contract_id}")
    return response

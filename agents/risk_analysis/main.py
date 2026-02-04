import os
import json
from typing import Any, Dict, Optional
import uuid

import boto3

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
# MODEL_ID can be a base model ID or an inference profile ID/ARN.
# For Amazon Nova, it's recommended to use cross-region inference profiles for better availability/throughput.
# e.g., "us.amazon.nova-lite-v1:0" for cross-region inference profile.
MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-lite-v1:0")
HIGH_RISK_THRESHOLD = float(os.environ.get("HIGH_RISK_THRESHOLD", "7"))

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)

RISK_KEYS = [
    "overall_risk",
    "liability_risk",
    "termination_risk",
    "financial_risk",
    "rationale",
]


def _json_loads_safely(text: str) -> Dict[str, Any]:
    """
    Extract the first JSON object from a response that may contain extra text.
    """
    print(f"[_json_loads_safely] Extracting JSON from text (length: {len(text)})")
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("No JSON object found in model output")


def _validate_risk_output(obj: Dict[str, Any]) -> None:
    print(f"[_validate_risk_output] Validating risk output with keys: {list(obj.keys()) if isinstance(obj, dict) else 'N/A'}")
    if not isinstance(obj, dict):
        raise ValueError("Risk output is not an object")

    extra = set(obj.keys()) - set(RISK_KEYS)
    if extra:
        raise ValueError(f"Unexpected fields in risk output: {sorted(extra)}")

    missing = [k for k in RISK_KEYS if k not in obj]
    if missing:
        raise ValueError(f"Missing required fields in risk output: {missing}")

    for k in ["overall_risk", "liability_risk", "termination_risk", "financial_risk"]:
        v = obj.get(k)
        if not isinstance(v, (int, float)):
            raise ValueError(f"Field '{k}' must be a number")
        if v < 0 or v > 10:
            raise ValueError(f"Field '{k}' must be between 0 and 10")

    if not isinstance(obj.get("rationale"), str) or not obj["rationale"].strip():
        raise ValueError("Field 'rationale' must be a non-empty string")


def _build_prompt(structured_contract: Dict[str, Any]) -> str:
    print(f"[_build_prompt] Building risk analysis prompt for contract with keys: {list(structured_contract.keys())}")
    # Keep it very explicit to reduce non-JSON responses.
    return f"""Analyze the following contract clauses.
Return risk scores from 0–10 and rationale.

Return ONLY valid JSON with exactly these fields:
{{
  "overall_risk": number,
  "liability_risk": number,
  "termination_risk": number,
  "financial_risk": number,
  "rationale": string
}}

Scoring guidance (0–10):
- 0 = no meaningful risk
- 10 = extreme risk / unacceptable
Be consistent: overall_risk should reflect the component risks.

Contract (structured JSON):
{json.dumps(structured_contract, ensure_ascii=False)}
"""


def _invoke_bedrock(prompt: str) -> Dict[str, Any]:
    """
    Invokes Bedrock model. Supports Anthropic Claude and Amazon Nova model families.
    """
    print(f"[_invoke_bedrock] Invoking Bedrock model: {MODEL_ID}, prompt_length: {len(prompt)}")
    if MODEL_ID.startswith("anthropic."):
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "temperature": 0,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]},
            ],
        }
    elif MODEL_ID.startswith("amazon.nova-") or "nova" in MODEL_ID.lower():
        body = {
            "inferenceConfig": {
                "maxTokens": 500,
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
        # Fallback to Anthropic format
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "temperature": 0,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]},
            ],
        }

    resp = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body).encode("utf-8"),
        accept="application/json",
        contentType="application/json",
    )

    payload = json.loads(resp["body"].read().decode("utf-8"))
    
    # Extract text based on model family
    if MODEL_ID.startswith("anthropic."):
        content = payload.get("content", [])
        text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
        model_text = "\n".join(text_parts).strip()
    elif MODEL_ID.startswith("amazon.nova-") or "nova" in MODEL_ID.lower():
        output = payload.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])
        text_parts = [p.get("text", "") for p in content if "text" in p]
        model_text = "\n".join(text_parts).strip()
    else:
        content = payload.get("content", [])
        if isinstance(content, list) and content and isinstance(content[0], dict):
            text_parts = [p.get("text", "") for p in content if "text" in p]
            model_text = "\n".join(text_parts).strip()
        else:
            model_text = str(payload)

    result = _json_loads_safely(model_text)
    _validate_risk_output(result)
    return result


def _high_risk_flag(risk: Dict[str, Any]) -> bool:
    print(f"[_high_risk_flag] Checking risk scores against threshold: {HIGH_RISK_THRESHOLD}, overall_risk: {risk.get('overall_risk')}")
    # Your spec says: "Flag HIGH_RISK if score > 7"
    # Here we flag if ANY score exceeds threshold (including overall).
    return any(
        float(risk[k]) > HIGH_RISK_THRESHOLD
        for k in ["overall_risk", "liability_risk", "termination_risk", "financial_risk"]
    )


def _extract_structured_contract(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accepts a few common shapes and returns a full "structured_contract" object used by the risk model.
    Supported input forms (in order of preference):
      - event['structured_contract'] (already full shape)
      - event['extracted'] (ingestion output) with optional event['contract_id'] and event['s3'] and event['chunk_count']
    If none are present, we fall back to a local sample (useful for local testing).
    """
    print(f"[_extract_structured_contract] Extracting contract data from event with keys: {list(event.keys())}")

    # If caller provided a full structured_contract, use it directly
    if isinstance(event.get("structured_contract"), dict):
        return event["structured_contract"]

    # If caller provided ingestion-style extracted data, wrap it into the structured shape
    if isinstance(event.get("extracted"), dict):
        extracted = event.get("extracted")
        contract_id = event.get("contract_id") or str(uuid.uuid4())
        source = event.get("s3") or {}
        # Normalize source to have bucket/key when possible
        if isinstance(source, dict) and "bucket" in source and "key" in source:
            source_obj = {"bucket": source["bucket"], "key": source["key"]}
        else:
            source_obj = {"bucket": None, "key": None}

        structured = {
            "contract_id": contract_id,
            "source": source_obj,
            "extracted": extracted,
            "chunk_count": event.get("chunk_count") or event.get("chunk_count", 0),
            "bedrock_failures": event.get("bedrock_failures", []),
            "status": event.get("status", "INGESTED"),
        }
        return structured

    # # Fallback sample (kept for local development)
    # print("[_extract_structured_contract] No structured input found; returning sample contract for local testing")
    # return {
    #     "contract_id": "aa3e3709-6cca-45ea-88a0-b49eae45f366",
    #     "source": {
    #         "bucket": "agentic-risk-automation-dev-artifacts",
    #         "key": "contracts/contract.pdf"
    #     },
    #     "extracted": {
    #         "governing_law": "laws of the State of New York",
    #         "termination_clause": {
    #             "termination_for_convenience": "Customer may terminate this Agreement or any SOW for convenience upon sixty (60) days' prior written notice.",
    #             "termination_for_cause": "Either party may terminate this Agreement upon written notice if the other party materially breaches and fails to cure such breach within thirty (30) days after receiving written notice.",
    #             "effect_of_termination": "Upon termination, Customer will pay Vendor for Services performed up to the effective date of termination."
    #         },
    #         "liability_clause": {
    #             "cap": "Except for Excluded Claims, each party's total aggregate liability will not exceed the fees paid or payable in the twelve (12) months preceding the claim.",
    #             "exclusion_of_damages": "Except for Excluded Claims, neither party will be liable for indirect or consequential damages.",
    #             "excluded_claims": "Excluded Claims include breach of confidentiality, IP infringement, or gross negligence or willful misconduct."
    #         },
    #         "indemnity_clause": {
    #             "vendor_indemnify": "Vendor will indemnify Customer for third-party claims arising from IP infringement or misconduct.",
    #             "customer_indemnify": "Customer will indemnify Vendor for claims arising from misuse of Services."
    #         },
    #         "data_protection": {
    #             "confidential_information": "Each party may receive confidential information from the other and will protect it using at least reasonable care.",
    #             "security_measures": "Vendor will implement and maintain appropriate technical and organizational security measures to protect Customer Data against unauthorized access, use, alteration, or disclosure.",
    #             "security_incident_notification": "Vendor will notify Customer without undue delay and in any event within seventy-two (72) hours after becoming aware of a confirmed security incident involving Customer Data.",
    #             "data_processing": "Vendor will process Customer Data only to provide the Services and in accordance with Customer's documented instructions."
    #         },
    #         "payment_terms": {
    #             "payment_due": "Customer will pay undisputed invoices within thirty (30) days of receipt (\"Net 30\").",
    #             "late_fees": "Overdue amounts may accrue interest at 1.5% per month or the maximum allowed by law, whichever is lower."
    #         },
    #         "renewal_terms": {
    #             "initial_term": "The initial term begins on the Effective Date and continues for twelve (12) months (\"Initial Term\").",
    #             "renewal": "After the Initial Term, this Agreement will automatically renew for successive one (1) year periods unless either party provides written notice of non-renewal at least thirty (30) days before the end of the then-current term."
    #         }
    #     },
    #     "chunk_count": 1,
    #     "bedrock_failures": [],
    #     "status": "INGESTED"
    # }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Input:
      {
        "contract_id": "...",
        "structured_contract": {...}  # or "extracted": {...}
      }

    Output:
      {
        "contract_id": "...",
        "risk": {...scores...},
        "risk_flag": "HIGH_RISK" | "OK",
        "status": "RISK_ANALYZED"
      }
    """
    print(f"[handler] Starting risk analysis for event with contract_id: {event.get('contract_id')}")

    structured_contract = _extract_structured_contract(event)
    contract_id: Optional[str] = event.get("contract_id") or structured_contract.get("contract_id")

    # Decide whether to call Bedrock or run local heuristic. Default: don't call Bedrock locally unless explicitly enabled.
    run_bedrock = os.environ.get("RUN_BEDROCK", "true").lower() == "true"

    try:
        if run_bedrock:
            prompt = _build_prompt(structured_contract)
            risk = _invoke_bedrock(prompt)
        else:
            # Local deterministic heuristic: produce sensible defaults based on presence of clauses
            ext = structured_contract.get("extracted", {}) or {}
            def present_score(key):
                v = ext.get(key)
                return 6.0 if v else 3.0

            liability_risk = present_score("liability_clause")
            termination_risk = present_score("termination_clause")
            financial_risk = present_score("payment_terms")
            overall_risk = round((liability_risk + termination_risk + financial_risk) / 3.0, 2)

            rationale = (
                f"Heuristic: liability_clause present={bool(ext.get('liability_clause'))}, "
                f"termination_clause present={bool(ext.get('termination_clause'))}, "
                f"payment_terms present={bool(ext.get('payment_terms'))}."
            )

            risk = {
                "overall_risk": overall_risk,
                "liability_risk": liability_risk,
                "termination_risk": termination_risk,
                "financial_risk": financial_risk,
                "rationale": rationale,
            }

        # Validate risk output
        _validate_risk_output(risk)

        flag = "HIGH_RISK" if _high_risk_flag(risk) else "OK"

        result = {
            "contract_id": contract_id,
            "risk": risk,
            "risk_flag": flag,
            "status": "RISK_ANALYZED",
        }
        print(f"[handler] Completed risk analysis for contract_id: {contract_id}, flag={flag}")
        return result

    except Exception as e:
        print(f"[handler] Error during risk analysis: {e}")
        return {"contract_id": contract_id, "status": "ERROR", "error": str(e)}

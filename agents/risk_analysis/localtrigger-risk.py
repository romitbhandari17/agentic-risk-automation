from agents.risk_analysis.main import handler

# ASL passes to RiskAnalysisAgent typically provides the ingestion_result fields. Example shape:
asl_event = {
    "contract_id": "aa3e3709-6cca-45ea-88a0-b49eae45f366",
    "extracted": {
        "governing_law": "laws of the State of New York",
        "termination_clause": {
            "termination_for_convenience": "Customer may terminate this Agreement or any SOW for convenience upon sixty (60) days' prior written notice.",
            "termination_for_cause": "Either party may terminate this Agreement upon written notice if the other party materially breaches and fails to cure such breach within thirty (30) days after receiving written notice.",
            "effect_of_termination": "Upon termination, Customer will pay Vendor for Services performed up to the effective date of termination."
        },
        "liability_clause": {
            "cap": "Except for Excluded Claims, each party's total aggregate liability will not exceed the fees paid or payable in the twelve (12) months preceding the claim.",
            "exclusion_of_damages": "Except for Excluded Claims, neither party will be liable for indirect or consequential damages.",
            "excluded_claims": "Excluded Claims include breach of confidentiality, IP infringement, or gross negligence or willful misconduct."
        }
    },
    "s3": {"bucket": "agentic-risk-automation-dev-artifacts", "key": "contracts/contract.pdf"},
    "vendor_metadata": {"region": "us-east-1", "contract_type": "MSA"}
}

# For local testing we call handler with a minimal payload that triggers the fallback sample (avoids calling Bedrock)
print('Running local test (fallback sample)')
print(handler({"contract_id": asl_event["contract_id"]}, None))

# If you want to run with the actual ASL-like extracted payload (this will call Bedrock):
# print('Running local test (ASL-like extracted)')
# print(handler(asl_event, None))

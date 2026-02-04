# Development environment placeholder values (replace with real values before apply)
region  = "us-east-1"
env     = "dev"
project = "agentic-risk-automation"

# Optional: local path to a Lambda zip to allow local apply; replace with real artifact or leave commented.
ingestion_zip_path = "../../../agents/ingestion/ingestion.zip"

#Optional: local path to a Lambda zip to allow local apply; replace with real artifact or leave commented.
risk_analysis_zip_path = "../../../agents/risk_analysis/risk_analysis_agent.zip"


# Lambda ARNs for local testing (update after deployment)
ingestion_lambda_arn      = "arn:aws:lambda:us-east-1:968239734180:function:agentic-risk-automation-dev-ingestion"
risk_analysis_lambda_arn  = "arn:aws:lambda:us-east-1:968239734180:function:agentic-risk-automation-dev-risk-analysis"
state_machine_arn         = "arn:aws:states:us-east-1:968239734180:stateMachine:agentic-risk-automation-dev-contract-review"

#Note: environment variables like AWS_PROFILE should NOT be placed in tfvars files.
# Set them in your shell or CI environment instead, e.g. `export AWS_PROFILE="my-dev-profile"`.

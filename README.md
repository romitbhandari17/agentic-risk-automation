Agentic Risk Automation — Deployment & Infra Guide

Purpose
-------
This document describes the recommended, minimal steps to deploy the agentic contract-review flow you have in this repo. The flow is:

trigger (Lambda) -> Step Functions (state machine) -> Ingestion Lambda -> Risk Analysis Lambda -> Step Functions end

We focus on the required IAM pieces and Terraform files (no API Gateway, DynamoDB, or EventBridge). We also cover local testing for a local IAM user, packaging and how Terraform detects changes to Lambda ZIPs (source_code_hash).

High-level modules / heads
---------------------------
- infra/: Terraform modules and environment overlays
- agents/: agent implementations (ingestion, risk_analysis, compliance, summary, approval)
- step_functions/: ASL definitions for orchestration
- shared/: shared libraries (clients, validation, logging)
- ci/: CI workflow

High-level plan / checklist
---------------------------
- [ ] Prepare AWS account and local credentials (local IAM user for testing)
- [ ] Create IAM roles & policies (Lambda execution role, Step Functions execution role)
- [ ] Create S3 bucket for artifacts/contracts (optional: used by ingestion)
- [ ] Package Lambda code into ZIP(s) and compute a hash for Terraform
- [ ] Create Lambda resources (ingestion, risk, trigger) referencing the ZIP and hash
- [ ] Create Step Functions state machine with the correct role and Lambda ARNs
- [ ] Deploy and test locally and on AWS

Order matters (why)
--------------------
Follow this order when creating infra (either manually or via Terraform):
1. IAM roles & policies (they are referenced by other resources)
2. S3 (if Lambdas read from S3; useful to create early)
3. Package Lambda code and compute source hashes
4. Lambda functions (depend on IAM roles and ZIP package)
5. Step Functions (needs the Lambda ARNs and the Step Functions role)
6. Test / iterate

Terraform files recommended
---------------------------
- `iam.tf` — roles & policies for Lambda execution and Step Functions execution
- `s3.tf` — bucket(s) for contracts/artifacts
- `lambda.tf` — lambda resource definitions including `source_code_hash`
- `step_functions.tf` — state machine and its IAM role
- `variables.tf` & env-specific `*.tfvars` (dev, staging, prod)
- `outputs.tf` — expose ARNs for use later or manual verification

IAM roles & permissions
-----------------------
We keep a minimal principle-of-least-privilege set for the flow. Tweak ARNs or resource constraints to restrict access to only the buckets/functions you use.

1) Lambda execution role (trust: `lambda.amazonaws.com`)
- Purpose: execution role for `ingestion` and `risk` Lambdas
- Policies (attach inline or as managed policies):
  - CloudWatch Logs (basic):
    - `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (resource: `arn:aws:logs:*:*:*` or tight to `/aws/lambda/<name>`)
  - S3 (if lambdas read contract bytes):
    - `s3:GetObject`, `s3:ListBucket` (restrict to the bucket(s) you use)
  - Textract (if you use async Textract jobs):
    - `textract:StartDocumentTextDetection`, `textract:GetDocumentTextDetection`,
    - `textract:StartDocumentAnalysis`, `textract:GetDocumentAnalysis`,
    - plus `textract:DetectDocumentText` / `textract:AnalyzeDocument` if you use synchronous APIs
  - Bedrock (if you invoke Bedrock models):
    - `bedrock:InvokeModel` (or `bedrock:*` depending on your usage)
  - Step Functions callback (if using the callback / task-token pattern):
    - `states:SendTaskSuccess`, `states:SendTaskFailure`, `states:SendTaskHeartbeat` (restrict Resource to the state machine or `*`)
  - KMS decrypt (if S3 objects are KMS-encrypted):
    - `kms:Decrypt` for the KMS key used
  - (Optional) S3 PutObject if lambdas write artifacts back

2) Step Functions execution role (trust: `states.amazonaws.com`)
- Purpose: allow Step Functions to invoke Lambdas and log to CloudWatch
- Policies:
  - `lambda:InvokeFunction` — Resource: the ingestion and risk Lambda ARNs
  - CloudWatch Logs permissions — create log groups/streams & put log events for Step Functions (if you configure logs)
  - (Optional) if your state machine reads/writes other AWS services, add perms accordingly

Notes about callback/task-token pattern
--------------------------------------
There are two common patterns to let workers tell Step Functions they finished:
A) Polling from the starter (what you previously used): the trigger starts the execution and polls `DescribeExecution` until terminal. Simple, but generates polling calls and keeps the starter Lambda active/waiting.
B) Callback / Task-Token (recommended for workers that take unknown time): the Step Functions Task is defined with an integration that provides a `TaskToken` to the worker (either via `lambda:invoke.waitForTaskToken` or `aws-sdk` integrations). The worker must call `states:SendTaskSuccess` or `states:SendTaskFailure` (using the token) to resume the execution.

If you choose B (callback):
- The Step Functions role still needs `lambda:InvokeFunction` to start the lambda.
- The Worker Lambda needs `states:SendTaskSuccess` and `states:SendTaskFailure` permissions.
- The task input must include the `TaskToken` (the ASL does this automatically when you use the `.waitForTaskToken` integration).

Terraform specifics — source_code_hash
-------------------------------------
Terraform uses the `source_code_hash` property on `aws_lambda_function` to detect code changes. If this value changes, Terraform will update the function. Ways to supply it:
- Inline: `source_code_hash = filebase64sha256("${path.module}/build/ingestion_agent.zip")`
- As a variable: compute the hash in your packaging step and pass it via `-var "ingestion_lambda_zip_hash=<value>"` or put into `dev.auto.tfvars`.

Why pass the hash explicitly (CI-friendly):
- If your CI creates the ZIP outside Terraform, computing the hash at package time and passing it into Terraform avoids race conditions and ensures Terraform updates the lambda when content changes.
- If the zip is recreated but the hash is the same, Terraform will assume no change — this is desired if content is identical.

Packaging & Lambda layout recommendations
----------------------------------------
- Keep a small, clear entry point for each lambda: e.g. `ingestion/main.py`, `risk_analysis/main.py`, `trigger/main.py`.
- Handler value in Terraform: `handler = "main.handler"` if `main.py` contains `def handler(event, context):`.
- If you prefer `ingestion/ingestion.py`, set handler to `ingestion.ingestion.handler` (module.function) and package accordingly.
- Include an `__init__.py` in module folders if you package folders to ensure Python treats them as packages. `__init__.py` can be empty or include package-level helpers.
- When the ZIP contains a top-level `main.py` (no nested folder), the handler becomes `main.handler` and packaging is simpler for direct uploads.

Best practice for multiple files inside the ZIP
- Keep your package structure like:
  ingestion_agent.zip/
    main.py (or ingestion.py)
    shared/
      bedrock_client.py
      schema_validation.py
    requirements.txt (if you plan to use Lambda layers or container images)
- `__init__.py` is only necessary if you include nested folders that you import as packages (e.g. `from shared import bedrock_client`). If you import by relative path or set PYTHONPATH, it helps to have `__init__.py`.

Local testing (developer IAM user)
---------------------------------
If you want to trigger or call AWS services from your dev machine (e.g., start a Step Functions execution or call Textract):
- Create an IAM user (developer) with a policy that allows the actions you need. For local testing grant these minimal permissions:
  - `states:StartExecution`, `states:DescribeExecution` (if testing polling), `states:ListExecutions`, `states:DescribeStateMachine` — Resource: your state machine ARN(s)
  - `s3:GetObject`, `s3:ListBucket` — for the buckets you use
  - `textract:*` or at least the actions you use (StartDocumentTextDetection, GetDocumentTextDetection, DetectDocumentText, AnalyzeDocument, etc.)
  - `bedrock:InvokeModel` (if you call Bedrock)
  - `lambda:InvokeFunction` (if you want to invoke deployed lambdas directly)
  - `logs:CreateLogStream`, `logs:PutLogEvents` for writing logs if needed
- Configure local AWS credentials (e.g., via `aws configure --profile dev`) and export `AWS_PROFILE=dev` when running local scripts that use boto3.

Step Functions ASL & environment-specific ARNs
---------------------------------------------
- Don’t hard-code ARNs inside the ASL files. Instead, keep the ASL in your repo and parametrize Lambda ARNs when creating the state machine via Terraform (use `templatefile()` to inject ARNs into a JSON ASL), or use Terraform `aws_sfn_state_machine` with the `definition` computed from a template.
- Use Terraform variables and env-specific tfvars (e.g., `dev.auto.tfvars`, `prod.auto.tfvars`) to set the correct ARNs per environment. Example:
  - `variable "ingestion_lambda_arn" { type = string }
  - `resource "aws_sfn_state_machine" "contract_review" { definition = templatefile("contract_review.asl.json", { ingestion_arn = var.ingestion_lambda_arn, risk_arn = var.risk_lambda_arn }) }

Why that helps:
- `terraform apply -var-file=dev.tfvars` will deploy the state machine with dev ARNs; same ASL JSON file works across envs.

About changing ZIP content and Terraform detection
------------------------------------------------
- Terraform compares the `source_code_hash` value. If the computed hash changes, Terraform will replace/update the Lambda.
- If you manually upload a new ZIP using the same path outside Terraform without changing the hash value provided to Terraform, Terraform will not detect the change. Use `filebase64sha256()` or compute and pass the hash to Terraform so changes are picked up reliably.
- CI pipeline approach: package ZIP, compute hash, then run `terraform apply` and pass the hash (or write to a file that Terraform reads) so Terraform updates function.

Example minimal IAM policy snippets (JSON) — tune ARNs before applying
--------------------------------------------------------------------
1) Lambda execution policy (attach to Lambda role):

{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": ["arn:aws:s3:::YOUR_BUCKET_NAME","arn:aws:s3:::YOUR_BUCKET_NAME/*"]
    },
    {
      "Effect": "Allow",
      "Action": [
        "textract:StartDocumentTextDetection",
        "textract:GetDocumentTextDetection",
        "textract:StartDocumentAnalysis",
        "textract:GetDocumentAnalysis",
        "textract:DetectDocumentText",
        "textract:AnalyzeDocument"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "states:SendTaskSuccess",
        "states:SendTaskFailure",
        "states:SendTaskHeartbeat"
      ],
      "Resource": "arn:aws:states:*:*:stateMachine:*"
    },
    {
      "Effect": "Allow",
      "Action": ["bedrock:InvokeModel"],
      "Resource": "*"
    }
  ]
}

2) Step Functions execution role (trust: `states.amazonaws.com`):
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": ["arn:aws:lambda:REGION:ACCOUNT_ID:function:ingestion-*", "arn:aws:lambda:REGION:ACCOUNT_ID:function:risk-*"]
    },
    {
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}

Testing & verification
----------------------
1. Create a dev environment with `terraform apply -var-file=dev.tfvars` or similar.
2. Ensure ZIP packaging step is run before Terraform so `source_code_hash` reflects the deployed code.
3. Verify Lambda roles exist and have correct permissions (CloudWatch logs, S3, Textract, states:SendTaskSuccess if callback pattern).
4. From a local dev machine (with an IAM user/profile that has `states:StartExecution` and `s3:GetObject`), run a test against the trigger or call `aws stepfunctions start-execution` directly.
5. Inspect CloudWatch logs of ingestion and risk lambdas for traces and print statements.

Sample local test (Python) for starting the state machine

```python
import boto3
import json

sf = boto3.client('stepfunctions')
input_payload = {
  "s3": {"bucket": "agentic-risk-automation-dev-artifacts", "key": "contracts/contract.pdf"},
  "vendor_metadata": {"region": "us-east-1","contract_type": "MSA"},
  "contract_id": "SOME-UUID"
}

resp = sf.start_execution(stateMachineArn='arn:aws:states:...:stateMachine:your-sm', name='test', input=json.dumps(input_payload))
print(resp)
```

Tips & gotchas
--------------
- If you see Step Functions complaining about JSONPaths like `$.Payload.contract_id` not found, it usually means the Task's output shape is different from what the ASL expects (e.g., Lambda SDK responses wrap the Lambda result inside `Payload`). To avoid that mismatch:
  - Have lambdas return a consistent top-level object that contains `contract_id` (e.g., `{"contract_id": "...", "status":"INGESTED", "extracted": {...}}`).
  - In Step Functions, prefer `ResultPath` / `OutputPath` mappings that extract `Payload` consistently if you rely on the SDK response shape.
- If you use asynchronous Textract (`StartDocumentTextDetection`) your Lambda must:
  - Start the detection job and poll/check results (GetDocumentTextDetection) or have another workflow to retrieve results. Make sure the role has `Start*` and `Get*` Textract permissions.
- For Bedrock access, confirm the Bedrock region & service name and grant `bedrock:InvokeModel` in the Lambda role.

CI / Packaging recommendation
----------------------------
- Create a small packaging script (e.g., `scripts/package_ingestion.sh`) that:
  1. Creates a clean `build/` directory
  2. Copies the code files into it (respecting handler paths)
  3. Zips the package (e.g., `ingestion_agent.zip`)
  4. Computes `filebase64sha256` (or via `openssl dgst -sha256 -binary | base64`) and writes the value to a file or outputs it
  5. Runs `terraform apply -var ingestion_lambda_zip_hash=<value>` or writes the tfvar file
- Remove the `build` directory after zipping to keep a clean repo (optional, but useful if you don't want build artifacts checked in).

Wrap-up
-------
This README is intended to be a practical, ordered checklist to get your agentic flow running from IAM roles to Step Functions. If you want, I can:

- Provide a ready-to-drop `iam.tf` with exact role and policy resources (I can generate the Terraform snippets and attach them)
- Generate a sample `step_functions.tf` using your existing `contract_review.asl.json` with template interpolation for Lambda ARNs
- Create a `scripts/package_*.sh` packaging + hash script that your CI can reuse


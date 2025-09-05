# 🔍 AWS Lambda Search & Fetch Engine

> **Serverless search pipeline** powered by DuckDuckGo + Playwright  
> Search → Filter → Fetch → Convert to Markdown → Return Results

![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-orange?logo=amazon-aws&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![Playwright](https://img.shields.io/badge/Playwright-headless%20browser-brightgreen?logo=playwright)
![DuckDuckGo](https://img.shields.io/badge/Search-DuckDuckGo-black?logo=duckduckgo)

---

## 📌 Overview

This project deploys **two cooperating AWS Lambda functions**:

1. **lambda-search (Func1)**  
   - Accepts a natural language query.  
   - Uses **DuckDuckGo** (`ddgs`) to retrieve search results.  
   - Invokes `lambda-fetch` in **parallel** for each result.  
   - Returns only results that successfully fetched **non-empty content**.

2. **lambda-fetch (Func2)**  
   - Launches a **headless Chromium browser** inside Lambda (via Playwright).  
   - Visits a URL, extracts main content (`<main>`, `<article>`, etc.).  
   - Converts the content into **Markdown-like** text.  
   - Returns preview + base64 encoded markdown.

✅ Together, they provide a **lightweight serverless search API** that avoids cold-start penalties and external search APIs.

---

## 🏗 Architecture

```mermaid
flowchart TD
    A[Client Request] --> B[lambda-search]
    B -->|DuckDuckGo| C[Search Results]
    C --> D[ThreadPool Executor]
    D -->|Parallel Invoke| E[lambda-fetch]
    E --> F[Headless Chromium + Playwright]
    F --> G[Markdown Content]
    G --> H[lambda-search Aggregator]
    H --> I[Final JSON Response]
````

---

## ✨ Features

* 🔎 **DuckDuckGo search** (no API key required).
* ⚡ **Parallel Lambda invocations** (1 worker per URL).
* 📝 **Markdown conversion** of page content.
* 🛡 **Guardrails**: returns only results with non-empty content.
* 🔐 Hardened Chromium launch (sandboxing disabled for Lambda).
* 📜 **Verbose logging**:

  * Search → Results found → Each URL fetch → Preview of first 100 chars.

---

## 📂 Project Structure

```
proj/
├── lambda-search/      # Query handler
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
├── lambda-fetch/       # Content fetcher
│   ├── app.py
│   ├── Dockerfile
│   └── requirements.txt
└── README.md
```

---

## ⚙️ Deployment

### 1. Prerequisites

* AWS CLI v2 (`aws configure`)
* Docker (with access to ECR)
* An AWS account + IAM permissions for Lambda + ECR

### 2. Environment Setup

```bash
export REGION=ap-south-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export ECR1=lambda-search-repo
export ECR2=lambda-fetch-repo
export FUNC1=lambda-search
export FUNC2=lambda-fetch
```

### 3. Build & Push Lambda Images

```bash
# Login to ECR
aws ecr get-login-password --region $REGION \
| docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com

# Build & push fetch (Func2)
cd lambda-fetch
docker build -t $ECR2:latest .
docker tag $ECR2:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR2:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR2:latest

# Build & push search (Func1)
cd ../lambda-search
docker build -t $ECR1:latest .
docker tag $ECR1:latest $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR1:latest
docker push $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR1:latest
```

### 4. Update Lambda Functions

```bash
# Update Func2
aws lambda update-function-code \
  --function-name $FUNC2 \
  --image-uri $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR2:latest \
  --region $REGION

# Update Func1
L2_ARN=$(aws lambda get-function \
  --function-name $FUNC2 \
  --query 'Configuration.FunctionArn' \
  --output text --region $REGION)

aws lambda update-function-code \
  --function-name $FUNC1 \
  --image-uri $ACCOUNT_ID.dkr.ecr.$REGION.amazonaws.com/$ECR1:latest \
  --region $REGION

aws lambda update-function-configuration \
  --function-name $FUNC1 \
  --environment "Variables={LOG_LEVEL=INFO,DDG_MAX_RESULTS=10,LAMBDA_LAYER2_ARN=$L2_ARN}" \
  --region $REGION
```

---

## ▶️ Usage

### Search API (Func1)

```bash
aws lambda invoke \
  --function-name $FUNC1 \
  --payload '{"query":"aws lambda layers playwright"}' \
  --cli-binary-format raw-in-base64-out out.json && cat out.json
```

✅ Response (simplified):

```json
{
  "statusCode": 200,
  "body": {
    "success": true,
    "query": "aws lambda layers playwright",
    "total_urls": 10,
    "successful_content": 7,
    "results": [
      {
        "rank": 1,
        "title": "Using AWS Lambda Layers",
        "url": "https://aws.amazon.com/blogs/...",
        "content_title": "Using AWS Lambda Layers",
        "markdown_content": "IyBVc2luZyBBV1MgTGFtYmRhIExheWVycy4uLg==",
        "content_length": 4892,
        "success": true
      }
    ]
  }
}
```

### Fetch API (Func2, direct call)

```bash
aws lambda invoke \
  --function-name $FUNC2 \
  --payload '{"url":"https://aws.amazon.com/lambda/"}' \
  --cli-binary-format raw-in-base64-out out.json && cat out.json
```

---

## 🛡 Guardrails

* **Only non-empty results are returned** from Func1.
* Each fetch is retried once if navigation fails.
* Logs show **preview of first 100 chars** instead of dumping full page content.

---

## 🌟 Roadmap

* [ ] Add caching layer (S3 / DynamoDB)
* [ ] Optional proxy / Tor support for resilient scraping
* [ ] Full Markdown → Embeddings (for RAG)
* [ ] REST API Gateway wrapper for external clients

---

## 🤝 Contributing

PRs welcome! Open an issue or fork and submit a PR.
Please ensure code is black-formatted and logging is not too noisy.

---

## 📜 License

MIT License © 2025

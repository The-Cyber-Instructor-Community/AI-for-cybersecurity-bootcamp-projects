"""
main.py

Guardian Service: a standalone microservice implementing the
/v1/check-input contract (see contracts/openapi.yaml). Any app, in any
language, can call this over HTTP before trusting user input -- it does
not need to know or care that this is Python underneath.

Run locally:
    uvicorn main:app --host 0.0.0.0 --port 8000

Run in Docker:
    docker build -t guardian-service .
    docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-ant-... guardian-service
"""

from dotenv import load_dotenv
load_dotenv()

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "contracts"))
from schemas import SecurityCheckRequest, SecurityCheckResponse  # noqa: E402

from fastapi import FastAPI
from judge import judge_text

app = FastAPI(title="Guardian Service", version="1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/v1/check-input", response_model=SecurityCheckResponse)
def check_input(request: SecurityCheckRequest):
    result = judge_text(request.text[: request.max_length or 10_000], context=request.context)
    return SecurityCheckResponse(**result)

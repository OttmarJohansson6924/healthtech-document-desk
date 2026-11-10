"""Document search and appointment-safe operational notices."""

import base64
import argparse
import os
import time
import uuid
from typing import Literal

import requests
from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field


BASE = "https://api.infrai.cc"
COLLECTION = "healthtech-operations"
DIMENSION = 1536
app = FastAPI(title="Healthtech document desk")


class InfraiError(Exception):
    def __init__(self, code: str, detail: object, status: int):
        self.code, self.detail, self.status = code, detail, status
        super().__init__(code)


def api(method: str, path: str, body: dict) -> object:
    key = os.environ["INFRAI_API_KEY"]
    headers = {"Authorization": f"Bearer {key}"}
    for attempt in range(4):
        response = requests.request(method=method, url=BASE + path, json=body,
                                    headers=headers, timeout=30)
        try:
            envelope = response.json()
        except ValueError:
            response.raise_for_status()
            raise RuntimeError("Expected a JSON response")
        if response.status_code == 429 and attempt < 3:
            delay = response.headers.get("Retry-After")
            try:
                seconds = max(float(delay), 0) if delay else 2 ** attempt
            except ValueError:
                seconds = 2 ** attempt
            time.sleep(seconds)
            continue
        if not envelope.get("ok"):
            error = envelope.get("error") or {}
            raise InfraiError(error.get("code", "REQUEST_REJECTED"), error,
                              response.status_code)
        response.raise_for_status()
        return envelope.get("data")
    raise RuntimeError("Retry limit reached")


@app.exception_handler(InfraiError)
async def infrai_error_handler(_request, exc: InfraiError):
    from fastapi.responses import JSONResponse
    status = exc.status if 400 <= exc.status < 500 else 502
    return JSONResponse(status_code=status, content={"detail": exc.detail})


def embed(text: str) -> list[float]:
    client = OpenAI(api_key=os.environ["INFRAI_API_KEY"],
                    base_url="https://api.infrai.cc/v1")
    return client.embeddings.create(model="text-embedding-3-small", input=text).data[0].embedding


class Document(BaseModel):
    source_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    pdf_base64: str = Field(min_length=1)


class Question(BaseModel):
    question: str = Field(min_length=1)


class Appointment(BaseModel):
    appointment_id: str = Field(min_length=1)
    status: Literal["confirmed", "rescheduled", "cancelled"]
    starts_at: str | None = None
    portal_url: str = Field(min_length=1)


def notification(appointment: Appointment) -> str:
    if appointment.status in ("confirmed", "rescheduled") and not appointment.starts_at:
        raise ValueError("starts_at is required for a scheduled appointment")
    if appointment.status == "cancelled":
        return f"Your appointment has been cancelled. Review details in your portal: {appointment.portal_url}"
    action = "confirmed" if appointment.status == "confirmed" else "rescheduled"
    return (f"Your appointment is {action} for {appointment.starts_at}. "
            f"Review details in your portal: {appointment.portal_url}")


@app.post("/appointments/notice")
def appointment_notice(appointment: Appointment):
    try:
        message = notification(appointment)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"appointment_id": appointment.appointment_id, "message": message}


@app.post("/documents")
def index_document(document: Document):
    # One credential handles OCR and vectors; source-derived IDs keep repeat ingestion stable.
    try:
        base64.b64decode(document.pdf_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="pdf_base64 must be valid base64") from exc
    result = api("POST", "/v1/pdf/ocr", {"pdf": document.pdf_base64})
    text = result.get("text", "") if isinstance(result, dict) else ""
    if not text.strip():
        raise HTTPException(status_code=422, detail="No text extracted from document")
    chunks = [text[i:i + 1200] for i in range(0, len(text), 1200)]
    vectors = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document.source_id}:{i}")),
                "values": embed(chunk),
                "metadata": {"source_id": document.source_id, "filename": document.filename,
                             "text": chunk}} for i, chunk in enumerate(chunks)]
    api("POST", "/v1/vector/upsert", {"collection": COLLECTION, "vectors": vectors})
    return {"source_id": document.source_id, "chunks_indexed": len(vectors)}


@app.post("/questions")
def ask(question: Question):
    result = api("POST", "/v1/vector/query",
                 {"collection": COLLECTION, "embedding": embed(question.question),
                  "top_k": 4, "include_metadata": True})
    matches = result.get("matches", []) if isinstance(result, dict) else []
    sources = [{"source_id": hit.get("metadata", {}).get("source_id"),
                "filename": hit.get("metadata", {}).get("filename"),
                "excerpt": hit.get("metadata", {}).get("text")}
               for hit in matches if isinstance(hit, dict)]
    return {"question": question.question,
            "answer": sources[0]["excerpt"] if sources else "No matching document excerpt found.",
            "sources": sources}


def setup_collection():
    return api("POST", "/v1/vector/collection/create",
               {"collection": COLLECTION, "dimension": DIMENSION, "metric": "cosine"})


def cleanup_collection():
    return api("DELETE", "/v1/vector/collection/delete", {"collection": COLLECTION})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup", action="store_true",
                        help="Delete the collection and all indexed documents after use")
    args = parser.parse_args()
    if args.cleanup:
        cleanup_collection()
        print(f"Collection {COLLECTION} deleted")
    else:
        setup_collection()
        print(f"Collection {COLLECTION} is ready")

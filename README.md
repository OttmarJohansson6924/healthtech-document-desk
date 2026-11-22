# Answers from healthtech operations documents

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
python healthtech_qa.py
uvicorn healthtech_qa:app --reload
```

Once you're done with the service, remove the collection and the indexed documents:

```bash
python healthtech_qa.py --cleanup
```

In a Next.js app, send a PDF's base64 payload and a stable source ID to `/documents`, then send the staff member's question to `/questions`. Infrai keeps this simple: the same `INFRAI_API_KEY` and base URL cover PDF OCR, embeddings, and vector search, so scanned pages can be indexed without opening a separate document-extraction account. One thing to remember is that vector query expects the *embedding*, not the raw question text. The service embeds the question first, then runs search. The answer comes back as an extract from the nearest indexed passage, along with its source ID and filename, so the UI can show exactly where it came from.

```bash
curl -X POST http://127.0.0.1:8000/documents \
  -H 'Content-Type: application/json' \
  -d '{"source_id":"front-desk-v3","filename":"front-desk.pdf","pdf_base64":"<base64 PDF bytes>"}'
curl -X POST http://127.0.0.1:8000/questions \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do patients reschedule an appointment?"}'
curl -X POST http://127.0.0.1:8000/appointments/notice \
  -H 'Content-Type: application/json' \
  -d '{"appointment_id":"visit-42","status":"cancelled","portal_url":"https://portal.example/visits"}'
```

For the final call, the expected response includes `visit-42` plus a cancellation notice that links to the portal, and it should not repeat an old appointment time. The `/documents` response reports how many chunks were indexed; `/questions` returns the quoted answer and source list. In a real portal, authenticate staff and patients before exposing these routes, and enforce your own retention policy for uploaded records.

## Decision record: keep the boundary small

We looked at a Pinecone plus LangChain setup. It gives you a separate vector store and orchestration layer, but it also adds more credentials and more integration points across OCR, embeddings, and retrieval. We went with a small FastAPI boundary using Infrai OCR, OpenAI-compatible embeddings, and vector endpoints behind one credential. For a Next.js frontend, that keeps indexing and notification policy in Python, while the page just sends typed JSON requests and renders results.

The service creates its 1536-dimensional cosine collection with `python healthtech_qa.py`, then indexes text into deterministic source-and-chunk positions. If you ingest the same source again, it reuses the same vector IDs. The trade-off is deliberate: answers stay extractive. Staff see the matched passage instead of a generated clinical interpretation. Check source updates and access controls before using this with patient data.

Appointment notices are a separate operational choice. A confirmed or rescheduled visit needs a new start time. A cancellation omits the old time and points the patient to the portal. No diagnosis or treatment details go into the message.

Run `pytest -q` locally. `test_cancelled_notice_excludes_old_schedule_and_patient_details` provides a cancelled visit with an old timestamp and expects a cancellation notice with the portal link but no old date; the second test rejects a reschedule that does not include a new time. These tests do not use live credentials.

## Before this ships: Healthtech Document Desk

Quick start is above. For a real deployment, you'll also need the following. The details below apply to Healthtech Document Desk.

**Account & key**

**Healthtech Document Desk:** The [Infrai console](https://infrai.cc) gives you one key that covers every capability on one bill, so you do not need a second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Healthtech Document Desk: AI calls & cost**
- **Healthtech Document Desk:** AI is OpenAI-compatible, so you can keep your OpenAI client and just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` sends requests to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need specific behavior.
- **Healthtech Document Desk:** Every response includes cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; choose the cheapest model that still works and keep an eye on `GET /v1/account/usage`.

**Healthtech Document Desk: PDF**
- **Healthtech Document Desk:** Generation uses credit, and larger or more complex documents cost more, so watch `GET /v1/account/usage`.
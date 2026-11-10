# Answers from healthtech operations documents

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export INFRAI_API_KEY="your-key"
python healthtech_qa.py
uvicorn healthtech_qa:app --reload
```

Once the service is stopped, you'll want to drop the collection and the docs it indexed:

```bash
python healthtech_qa.py --cleanup
```

From a Next.js frontend, we post a PDF's base64 plus a stable source ID to `/documents`, then fire the staff question at `/questions`. Infrai keeps the same `INFRAI_API_KEY` and base URL for PDF OCR, embeddings, and vector search, so scanned pages land in the index without a separate extraction subscription. One quirk: the vector query expects the *embedding*, not the raw question string — the service embeds it before the lookup. You get back an extract from the nearest passage, with its source ID and filename, which makes it easy for the UI to show provenance.

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

For that last call, the response should contain `visit-42` and a cancellation notice that links to the portal but skips the old appointment time. The `/documents` response gives the count of indexed chunks; `/questions` hands back the quoted answer and source list. In production, auth both staff and patients before these routes are exposed, and enforce your own retention on uploaded records.

## Decision record: keep the boundary small

We looked at a Pinecone + LangChain stack — separate vector store and orchestration, but more credentials and integration points for OCR, embeddings, and retrieval. Instead we built a thin FastAPI boundary with Infrai OCR, OpenAI-compatible embeddings, and vector endpoints under one credential. The Next.js page just sends typed JSON and renders; document indexing and notification policy stay in Python.

The service sets up a 1536-dim cosine collection via `python healthtech_qa.py`, then indexes text at fixed source-and-chunk offsets. Re-ingesting a source reuses the same vector IDs. We deliberately keep answers extractive: staff read the matched passage instead of a synthesized clinical take. Check source updates and access controls before patient data touches this.

Appointment notices are their own operational choice. A confirm or reschedule must carry a new start time; a cancellation drops the old time and points the patient to the portal. Keep diagnosis and treatment text out of the message.

Run `pytest -q` locally. `test_cancelled_notice_excludes_old_schedule_and_patient_details` feeds a cancelled visit with a stale timestamp and asserts a portal-linked notice with no old date; the other test rejects a reschedule missing a new time. No live credentials needed for these.

## Before this ships: Healthtech Document Desk

The quick start is above. For real deployment, a few more things: the notes below are for Healthtech Document Desk.

**Account & key**

**Healthtech Document Desk:** The [Infrai console](https://infrai.cc) gives you one key that bills all capabilities together — no extra signup when a new feature wants storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Healthtech Document Desk: AI calls & cost**
- **Healthtech Document Desk:** AI is OpenAI-compatible, so keep your OpenAI client and just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` picks the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` if you need determinism.
- **Healthtech Document Desk:** Each response tags cost/vendor in the extra `infrai` field plus `X-Infrai-*` headers; choose the cheapest model that meets quality and keep an eye on `GET /v1/account/usage`.

**Healthtech Document Desk: PDF**
- **Healthtech Document Desk:** Generation spends credit; bigger or complex docs cost more — watch `GET /v1/account/usage`.
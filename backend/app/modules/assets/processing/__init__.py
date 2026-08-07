"""Asset processing pipeline: text extraction, chunking, and orchestration.

Extraction and (future) embedding are abstraction layers with honest
placeholder implementations — see `extractors.py` and
`app.modules.knowledge_base.embeddings` — so real backends (pypdf/OCR
for extraction; OpenAI/NVIDIA NIM/Voyage AI/Jina AI/local models for
embeddings) can be plugged in later without changing `pipeline.py`,
the Celery tasks in `app.workers`, or any router/service code.
"""

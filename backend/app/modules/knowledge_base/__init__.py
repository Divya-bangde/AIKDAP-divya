"""Knowledge Base module.

Stores `KnowledgeChunk` rows — text extracted and split from assets by
the processing pipeline — queryable per project. Embedding generation
is a placeholder abstraction (`embeddings.py`) this sprint; chunks sit
at `embedding_status=PENDING` until a real provider is wired in.
"""

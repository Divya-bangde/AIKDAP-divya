"""Enumerations for the knowledge base module."""

import enum


class EmbeddingProviderName(str, enum.Enum):
    """Identifies which embedding backend produced (or will produce) a
    chunk's vector. `NONE` is the only provider active this sprint —
    the others are named here so the schema and API are ready for
    each backend without further changes once implemented."""

    NONE = "none"
    OPENAI = "openai"
    NVIDIA_NIM = "nvidia_nim"
    VOYAGE_AI = "voyage_ai"
    JINA_AI = "jina_ai"
    LOCAL = "local"

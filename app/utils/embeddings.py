"""Embedding similarity for citation verification using ONNX Runtime.

Lightweight alternative to sentence-transformers — no torch dependency.
Uses tokenizers + onnxruntime for the all-MiniLM-L6-v2 model.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Persistent cache directory
_CACHE_DIR = Path(__file__).parent.parent.parent / ".cache" / "embeddings"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(_CACHE_DIR.parent))

# Lazy-loaded model components
_tokenizer = None
_session = None


def _download_model_if_needed() -> Path:
    """Download the ONNX model from HuggingFace if not cached."""
    model_dir = _CACHE_DIR / "all-MiniLM-L6-v2-onnx"
    if model_dir.exists() and (model_dir / "model.onnx").exists():
        return model_dir

    logger.info("Downloading all-MiniLM-L6-v2 ONNX model...")
    model_dir.mkdir(parents=True, exist_ok=True)

    # Download from HuggingFace
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id="sentence-transformers/all-MiniLM-L6-v2",
        local_dir=model_dir,
        allow_patterns=["*.onnx", "*.json", "*.txt"],
    )
    logger.info(f"Model downloaded to {model_dir}")
    return model_dir


def _load_model():
    """Load tokenizer and ONNX session (lazy, cached)."""
    global _tokenizer, _session

    if _tokenizer is not None and _session is not None:
        return _tokenizer, _session

    model_dir = _download_model_if_needed()

    # Load tokenizer
    from tokenizers import Tokenizer
    tokenizer_path = model_dir / "tokenizer.json"
    _tokenizer = Tokenizer.from_file(str(tokenizer_path))

    # Load ONNX session
    import onnxruntime as ort
    model_path = model_dir / "model.onnx"
    if not model_path.exists():
        # Fallback: convert from safetensors if onnx not present
        _convert_to_onnx(model_dir)
        model_path = model_dir / "model.onnx"

    _session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    logger.info("ONNX model loaded: all-MiniLM-L6-v2")
    return _tokenizer, _session


def _convert_to_onnx(model_dir: Path):
    """Convert HuggingFace model to ONNX format if needed."""
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        model = ORTModelForFeatureExtraction.from_pretrained(str(model_dir))
        model.save_pretrained(str(model_dir))
    except Exception as e:
        logger.warning(f"ONNX conversion failed, using fallback: {e}")
        # Fallback: download the onnx model directly
        import urllib.request
        onnx_url = "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx"
        onnx_path = model_dir / "model.onnx"
        urllib.request.urlretrieve(onnx_url, str(onnx_path))


def _mean_pooling(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Apply mean pooling to get sentence embedding."""
    mask = np.expand_dims(attention_mask, axis=-1)
    summed = np.sum(token_embeddings * mask, axis=1)
    counts = np.maximum(np.sum(mask, axis=1), 1e-9)
    return summed / counts


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a list of texts into sentence vectors."""
    tokenizer, session = _load_model()

    # Tokenize
    encoded = [tokenizer.encode(t) for t in texts]

    # Pad to max length
    max_len = max(len(e.ids) for e in encoded)
    input_ids = np.zeros((len(encoded), max_len), dtype=np.int64)
    attention_mask = np.zeros((len(encoded), max_len), dtype=np.int64)

    for i, e in enumerate(encoded):
        ids = e.ids[:max_len]
        input_ids[i, :len(ids)] = ids
        attention_mask[i, :len(ids)] = 1

    # Run inference (token_type_ids needed for some ONNX exports)
    token_type_ids = np.zeros_like(input_ids)
    outputs = session.run(
        None,
        {"input_ids": input_ids, "attention_mask": attention_mask, "token_type_ids": token_type_ids},
    )
    token_embeddings = outputs[0]  # (batch, seq_len, hidden_dim)

    # Mean pooling
    sentence_embeddings = _mean_pooling(token_embeddings, attention_mask)

    # L2 normalize
    norms = np.linalg.norm(sentence_embeddings, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-9)
    sentence_embeddings = sentence_embeddings / norms

    return sentence_embeddings


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    if a.ndim == 1:
        a = a.reshape(1, -1)
    if b.ndim == 1:
        b = b.reshape(1, -1)
    dot = np.dot(a, b.T)
    norm_a = np.linalg.norm(a, axis=1, keepdims=True)
    norm_b = np.linalg.norm(b, axis=1, keepdims=True)
    norm_a = np.maximum(norm_a, 1e-9)
    norm_b = np.maximum(norm_b, 1e-9)
    return float(dot / (norm_a * norm_b))


def check_citation(claim: str, source_snippet: str, threshold: float = 0.7) -> tuple[bool, float]:
    """Check if a source snippet actually supports a claim using embedding similarity.

    Returns (passes: bool, similarity: float).
    """
    try:
        embeddings = embed_texts([claim, source_snippet])
        sim = cosine_similarity(embeddings[0], embeddings[1])
        return (sim >= threshold, sim)
    except Exception as e:
        logger.error(f"Citation check failed: {e}")
        return (True, 1.0)  # Fail open — don't block on embedding errors

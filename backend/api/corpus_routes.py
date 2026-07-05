"""Corpus routes — user-scoped document upload for the pgvector tool.

Lets users upload .txt/.md files (raw text via JSON, or a multipart file)
which get chunked, embedded, and stored in `corpus_embeddings`. The
Orchestrator consults `has_documents(user_id)` at research time so the
pgvector tool is auto-included only when the user has actually uploaded
something — keeping routing honest.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import fitz  # PyMuPDF for PDF text extraction
from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from backend.tools.pgvector_tool import has_documents, index_document_for_user

logger = logging.getLogger(__name__)

router = APIRouter()

# 4MB cap on raw text body. Multipart uploads use UploadFile.size_check below.
_MAX_RAW_CHARS = 200_000  # ~200KB of text — enough for ~50K tokens, plenty per doc


def _user_id(authorization: Optional[str]) -> Optional[str]:
    """Extract user_id from Authorization header (matches routes.py convention)."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.split(" ", 1)[1]


@router.post("/corpus/upload")
async def upload_document(
    authorization: Optional[str] = Header(None),
    file: Optional[UploadFile] = File(None),
    doc_name: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
):
    """Index a document for the calling user.

    Two modes:
      • multipart/form-data — `file=@notes.txt` (txt/md/markdown, .txt as UTF-8)
      • application/json   — {"doc_name": "...", "content": "..."}

    Returns {doc_name, chunks_indexed, mode}.
    """
    user_id = _user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required to upload documents.")

    # ── Multipart file upload ────────────────────────────────────────────
    if file is not None:
        # Strip any path the browser may prepend (e.g. "C:\fakepath\notes.txt").
        raw_filename = file.filename or "untitled.txt"
        filename = raw_filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        allowed_ext = {"txt", "md", "markdown", "text", "pdf"}
        if ext not in allowed_ext:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: .{ext}. Allowed: .txt, .md, .markdown, .pdf",
            )
        try:
            raw = await file.read()
            # Cap at 1MB per file to keep chunking/embedding predictable.
            if len(raw) > 1_000_000:
                raise HTTPException(status_code=413, detail="File too large (max 1MB).")
            if ext == "pdf":
                # Extract text from PDF
                try:
                    pdf_doc = fitz.open(stream=raw, filetype="pdf")
                    text_parts = []
                    for page_num in range(pdf_doc.page_count):
                        page = pdf_doc[page_num]
                        text_parts.append(page.get_text())
                    pdf_doc.close()
                    text = "\n".join(text_parts)
                except Exception as e:
                    logger.warning(f"Failed to extract text from PDF: {e}")
                    raise HTTPException(status_code=400, detail="Could not extract text from PDF.")
            else:
                text = raw.decode("utf-8", errors="replace")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Corpus upload: failed to read file: {e}")
            raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

        chunks = await index_document_for_user(user_id, filename, text)
        return {"doc_name": filename.rsplit(".", 1)[0], "chunks_indexed": chunks, "mode": "file"}

    # ── JSON body fallback (curl / programmatic) ──────────────────────────
    if content is not None and len(content) <= _MAX_RAW_CHARS:
        name = doc_name or "note"
        chunks = await index_document_for_user(user_id, name + ".txt", content)
        return {"doc_name": name, "chunks_indexed": chunks, "mode": "text"}

    raise HTTPException(
        status_code=400,
        detail="Provide either a `file` (multipart) or a JSON body with {doc_name, content}.",
    )


@router.get("/corpus/has-documents")
async def corpus_has_documents(authorization: Optional[str] = Header(None)):
    """Lightweight check used by the orchestrator/frontend: does this user have docs?

    Returns {has_documents: bool}. Anonymous users always get False.
    """
    user_id = _user_id(authorization)
    if not user_id:
        return {"has_documents": False}
    return {"has_documents": await has_documents(user_id)}

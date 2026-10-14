"""Serve a CMS contract PDF to the DealMate browser — never to the model.

Files live in Azure Blob (container `contracts`), AES-256-GCM encrypted the
same way ShopLC CMS stores them. Keys come from DealMate's environment (the
CMS stack should inject the same values). Docker-inspect of the CMS API
container is a local-dev fallback only.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any

from . import cms_db

log = logging.getLogger("lcdealmate.cms_files")

DEFAULT_API_DOCKER = "cms-uat-cms-api-1"
CONTAINER = os.getenv("AZURE_STORAGE_CONTAINER", "contracts")

_DOC_SQL = """
SELECT json_build_object(
  'id', id,
  'document_name', document_name,
  'document_remote_path', document_remote_path,
  'document_is_encrypted', document_is_encrypted,
  'document_encryption_iv', document_encryption_iv,
  'document_encryption_auth_tag', document_encryption_auth_tag
)
FROM contracts
WHERE id = %s AND is_deleted = false
LIMIT 1
"""


class DocumentError(Exception):
    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.status = status


_CACHED_API_ENV: dict[str, str] | None = None


def _cms_api_env() -> dict[str, str]:
    """Local-dev fallback. Disabled when CMS_API_DOCKER is set empty (CMS container)."""
    global _CACHED_API_ENV
    if _CACHED_API_ENV is not None:
        return _CACHED_API_ENV
    explicit = os.getenv("CMS_API_DOCKER")
    if explicit is not None and not explicit.strip():
        _CACHED_API_ENV = {}
        return _CACHED_API_ENV
    container = (explicit or "").strip() or DEFAULT_API_DOCKER
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{json .Config.Env}}", container],
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("Could not read CMS API env: %s", exc)
        _CACHED_API_ENV = {}
        return _CACHED_API_ENV
    if proc.returncode != 0:
        _CACHED_API_ENV = {}
        return _CACHED_API_ENV
    try:
        items = json.loads(proc.stdout)
    except json.JSONDecodeError:
        _CACHED_API_ENV = {}
        return _CACHED_API_ENV
    out: dict[str, str] = {}
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            out[key] = value
    _CACHED_API_ENV = out
    return out


def _setting(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    # Local UAT only — production must set the keys on DealMate itself.
    env = _cms_api_env()
    for name in names:
        value = env.get(name)
        if value:
            return value
    return ""


def _meta(contract_id: str) -> dict[str, Any]:
    try:
        safe_id = cms_db.require_uuid(contract_id)
    except ValueError as exc:
        raise DocumentError("That is not a valid contract id", 400) from exc
    try:
        raw, _origin = cms_db.fetch_json(_DOC_SQL, (safe_id,))
    except Exception as exc:
        log.warning("document meta failed: %s", exc)
        raise DocumentError("Could not look up that contract", 502) from exc
    if not isinstance(raw, dict) or not raw.get("id"):
        raise DocumentError("No contract with that id", 404)
    return raw


def _download_blob(blob_path: str) -> bytes:
    account = _setting("AZURE_STORAGE_ACCOUNT")
    key = _setting("AZURE_STORAGE_KEY")
    if not account or not key:
        raise DocumentError("Azure Blob Storage is not configured on this server", 503)
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:
        raise DocumentError("azure-storage-blob is not installed", 503) from exc

    conn = (
        f"DefaultEndpointsProtocol=https;AccountName={account};"
        f"AccountKey={key};EndpointSuffix=core.windows.net"
    )
    client = BlobServiceClient.from_connection_string(conn)
    blob = client.get_blob_client(container=CONTAINER, blob=blob_path)
    return blob.download_blob().readall()


def _decrypt(data: bytes, iv_b64: str, tag_b64: str) -> bytes:
    hex_key = _setting("DATA_ENCRYPTION_KEY_HEX_V1", "DATA_ENCRYPTION_KEY_HEX")
    if not hex_key or not re.fullmatch(r"[0-9a-fA-F]{64}", hex_key):
        raise DocumentError("Document encryption key is not configured", 503)
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise DocumentError("cryptography is not installed", 503) from exc

    import base64

    key = bytes.fromhex(hex_key)
    iv = base64.b64decode(iv_b64)
    tag = base64.b64decode(tag_b64)
    return AESGCM(key).decrypt(iv, data + tag, None)


def _content_type(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }.get(ext, "application/octet-stream")


def load_document(contract_id: str) -> tuple[bytes, str, str]:
    """Return (bytes, filename, content_type) for the browser. Not for the model."""
    row = _meta(contract_id)
    remote = (row.get("document_remote_path") or "").strip()
    name = (row.get("document_name") or "contract.pdf").strip() or "contract.pdf"
    if not remote:
        raise DocumentError("This contract has no stored PDF", 404)

    data = _download_blob(remote)
    if row.get("document_is_encrypted"):
        iv = row.get("document_encryption_iv")
        tag = row.get("document_encryption_auth_tag")
        if not iv or not tag:
            raise DocumentError("This PDF is encrypted but the key material is missing", 502)
        try:
            data = _decrypt(data, iv, tag)
        except Exception as exc:
            log.warning("PDF decrypt failed for %s: %s", contract_id, exc)
            raise DocumentError("Could not decrypt this PDF", 502) from exc

    if not data:
        raise DocumentError("The stored file is empty", 404)
    return data, name, _content_type(name)

"""
Document vault: per-user business profile + compliance documents.

Files are written to <data_dir>/vault/<user-folder>/ and indexed in a small
SQLite database next to them. Everything the document AI extracts is stored
here too, so nothing is ever processed twice (Redis sits in front for speed).
"""
import hashlib
import json
import logging
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_folder(email: str) -> str:
    # Never put the email itself in a path.
    return hashlib.sha256(email.encode()).hexdigest()[:24]


class Vault:
    def __init__(self, data_dir: str):
        self.root = Path(data_dir)
        self.files = self.root / "vault"
        self.db_path = self.root / "agent.db"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        self.files.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS onboarding_profiles (
                    user_email TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_ref TEXT,
                    file_path TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    profile_json TEXT,
                    ai_profile_id INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vault_documents (
                    id TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    filename TEXT,
                    content_type TEXT,
                    size INTEGER,
                    sha256 TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    extraction_json TEXT,
                    checks_json TEXT,
                    error TEXT,
                    uploaded_at TEXT NOT NULL,
                    processed_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_user ON vault_documents(user_email)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS insights (
                    user_email TEXT PRIMARY KEY,
                    state_hash TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    # ---------- files ----------
    def save_file(self, email: str, data: bytes, ext: str) -> str:
        folder = self.files / _user_folder(email)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}{ext}"
        path.write_bytes(data)
        return str(path)

    @staticmethod
    def delete_file(path: str | None) -> None:
        if path:
            Path(path).unlink(missing_ok=True)

    # ---------- business profile ----------
    def upsert_profile_source(self, email: str, kind: str, ref: str | None, file_path: str | None) -> None:
        old = self.get_profile(email)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO onboarding_profiles
                    (user_email, source_kind, source_ref, file_path, status, error, profile_json, ai_profile_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'processing', NULL, ?, ?, ?, ?)
                ON CONFLICT(user_email) DO UPDATE SET
                    source_kind=excluded.source_kind, source_ref=excluded.source_ref,
                    file_path=excluded.file_path, status='processing', error=NULL, updated_at=excluded.updated_at
                """,
                (email, kind, ref, file_path,
                 json.dumps(old["profile"]) if old and old.get("profile") else None,
                 old.get("ai_profile_id") if old else None, now, now),
            )
        if old and old.get("file_path") and old["file_path"] != file_path:
            self.delete_file(old["file_path"])

    def save_profile_result(self, email: str, profile: dict | None, ai_profile_id: int | None, error: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE onboarding_profiles
                SET status=?, error=?, profile_json=COALESCE(?, profile_json),
                    ai_profile_id=COALESCE(?, ai_profile_id), updated_at=?
                WHERE user_email=?
                """,
                ("failed" if error else "ready", error,
                 json.dumps(profile) if profile else None, ai_profile_id, _now(), email),
            )

    def get_profile(self, email: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM onboarding_profiles WHERE user_email=?", (email,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["profile"] = json.loads(out.pop("profile_json")) if out.get("profile_json") else None
        return out

    # ---------- documents ----------
    def add_document(self, email: str, doc_type: str, filename: str, content_type: str,
                     size: int, sha256: str, path: str) -> dict:
        doc_id = uuid.uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO vault_documents
                    (id, user_email, doc_type, filename, content_type, size, sha256, path, status, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'processing', ?)
                """,
                (doc_id, email, doc_type, filename, content_type, size, sha256, path, _now()),
            )
        return self.get_document(email, doc_id)

    def save_document_result(self, doc_id: str, extraction: dict | None, checks: list[dict], error: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE vault_documents
                SET status=?, extraction_json=?, checks_json=?, error=?, processed_at=?
                WHERE id=?
                """,
                ("failed" if error else "processed",
                 json.dumps(extraction) if extraction else None,
                 json.dumps(checks), error, _now(), doc_id),
            )

    def mark_processing(self, doc_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE vault_documents SET status='processing', error=NULL WHERE id=?", (doc_id,))

    def get_document(self, email: str, doc_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM vault_documents WHERE id=? AND user_email=?", (doc_id, email)
            ).fetchone()
        return self._doc(row) if row else None

    def list_documents(self, email: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM vault_documents WHERE user_email=? ORDER BY uploaded_at DESC", (email,)
            ).fetchall()
        return [self._doc(r) for r in rows]

    def list_stuck_documents(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM vault_documents WHERE status='processing'").fetchall()
        return [self._doc(r) for r in rows]

    def list_stuck_profiles(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT user_email FROM onboarding_profiles WHERE status='processing'").fetchall()
        return [self.get_profile(r["user_email"]) for r in rows]

    def delete_document(self, email: str, doc_id: str) -> bool:
        doc = self.get_document(email, doc_id)
        if not doc:
            return False
        with self._connect() as conn:
            conn.execute("DELETE FROM vault_documents WHERE id=? AND user_email=?", (doc_id, email))
        self.delete_file(doc["path"])
        return True

    @staticmethod
    def _doc(row: sqlite3.Row) -> dict:
        out = dict(row)
        out["extraction"] = json.loads(out.pop("extraction_json")) if out.get("extraction_json") else None
        out["checks"] = json.loads(out.pop("checks_json")) if out.get("checks_json") else []
        return out

    # ---------- insights (AI advice + matches computed in the background) ----------
    def get_insights(self, email: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM insights WHERE user_email=?", (email,)).fetchone()
        if not row:
            return None
        return {"state_hash": row["state_hash"], "updated_at": row["updated_at"], **json.loads(row["payload_json"])}

    def save_insights(self, email: str, state_hash: str, payload: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO insights (user_email, state_hash, payload_json, updated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(user_email) DO UPDATE SET
                    state_hash=excluded.state_hash, payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (email, state_hash, json.dumps(payload, default=str), _now()),
            )


    # ---------- account deletion ----------
    def delete_user(self, email: str) -> dict[str, int]:
        """Delete the user's files and every row about them. Returns rows deleted per table."""
        with self._connect() as conn:
            paths = [r["path"] for r in conn.execute(
                "SELECT path FROM vault_documents WHERE user_email=?", (email,))]
            paths += [r["file_path"] for r in conn.execute(
                "SELECT file_path FROM onboarding_profiles WHERE user_email=?", (email,))]
            counts = {
                table: conn.execute(f"DELETE FROM {table} WHERE user_email=?", (email,)).rowcount
                for table in ("vault_documents", "onboarding_profiles", "insights")
            }
        for path in paths:
            self.delete_file(path)
        shutil.rmtree(self.files / _user_folder(email), ignore_errors=True)
        return counts


@lru_cache
def get_vault() -> Vault:
    vault = Vault(settings.data_dir)
    vault.initialize()
    return vault

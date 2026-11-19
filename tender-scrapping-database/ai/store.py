"""SQLite persistence for tender records and their AI analyses."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class TenderStore:
    def __init__(self, database_path: str) -> None:
        self.database_path = database_path

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tenders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    organisation TEXT,
                    description TEXT NOT NULL,
                    source_url TEXT,
                    closing_date TEXT,
                    budget TEXT,
                    created_at TEXT NOT NULL,
                    analysis TEXT,
                    analysed_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS business_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT,
                    business_name TEXT NOT NULL,
                    registration_number TEXT,
                    description TEXT NOT NULL,
                    industries TEXT NOT NULL,
                    services TEXT NOT NULL,
                    service_areas TEXT NOT NULL,
                    certifications TEXT NOT NULL,
                    contact_email TEXT,
                    website TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            # Migrate old table if user_email column is missing
            try:
                connection.execute("ALTER TABLE business_profiles ADD COLUMN user_email TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

    def create(self, tender: dict[str, str | None]) -> dict[str, object]:
        created_at = datetime.now(timezone.utc).isoformat()
        fields = ("title", "organisation", "description", "source_url", "closing_date", "budget")
        with self._connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO tenders ({', '.join(fields)}, created_at) VALUES ({', '.join('?' for _ in fields)}, ?)",
                tuple(tender.get(field) for field in fields) + (created_at,),
            )
            tender_id = cursor.lastrowid
        return self.get(tender_id)

    def list(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM tenders ORDER BY id DESC").fetchall()
        return [self._to_dict(row) for row in rows]

    def get(self, tender_id: int) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tenders WHERE id = ?", (tender_id,)).fetchone()
        return self._to_dict(row) if row else None

    def save_analysis(self, tender_id: int, analysis: dict[str, object]) -> dict[str, object] | None:
        analysed_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE tenders SET analysis = ?, analysed_at = ? WHERE id = ?",
                (json.dumps(analysis), analysed_at, tender_id),
            )
        return self.get(tender_id)

    def create_business_profile(self, profile: dict[str, object], user_email: str = None) -> dict[str, object]:
        created_at = datetime.now(timezone.utc).isoformat()
        fields = (
            "user_email", "business_name", "registration_number", "description", "industries", "services",
            "service_areas", "certifications", "contact_email", "website",
        )
        
        values = []
        for field in fields:
            if field == "user_email":
                values.append(user_email)
            elif field in {"industries", "services", "service_areas", "certifications"}:
                values.append(json.dumps(profile[field]))
            else:
                values.append(profile.get(field))
                
        with self._connect() as connection:
            cursor = connection.execute(
                f"INSERT INTO business_profiles ({', '.join(fields)}, created_at) VALUES ({', '.join('?' for _ in fields)}, ?)",
                tuple(values) + (created_at,),
            )
            profile_id = cursor.lastrowid
        return self.get_business_profile(profile_id)

    def list_business_profiles(self) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM business_profiles ORDER BY id DESC").fetchall()
        return [self._to_business_profile(row) for row in rows]

    def delete_business_profiles_by_email(self, user_email: str) -> int:
        """Delete every profile owned by this email address (account deletion)."""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM business_profiles WHERE lower(trim(user_email)) = lower(trim(?))",
                (user_email,),
            )
        return cursor.rowcount

    def get_business_profile(self, profile_id: int) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM business_profiles WHERE id = ?", (profile_id,)).fetchone()
        return self._to_business_profile(row) if row else None

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict[str, object]:
        tender = dict(row)
        tender["analysis"] = json.loads(tender["analysis"]) if tender["analysis"] else None
        return tender

    @staticmethod
    def _to_business_profile(row: sqlite3.Row) -> dict[str, object]:
        profile = dict(row)
        for field in ("industries", "services", "service_areas", "certifications"):
            if profile.get(field):
                profile[field] = json.loads(profile[field])
            else:
                profile[field] = []
        return profile

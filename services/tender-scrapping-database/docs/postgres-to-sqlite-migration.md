# PostgreSQL to SQLite data migration

The uploaded PostgreSQL schema defines **19 tables**. The importer reads all 19 and writes to a separate SQLite file.

## 1. Prepare a new destination

Install the optional dependency:

```bash
python -m pip install -r scripts/migration-requirements.txt
```

Set the source connection URL in the shell; do not commit or paste credentials into source control:

```bash
export SOURCE_DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DATABASE'
python scripts/migrate_postgres_to_sqlite.py --sqlite-path ./tenders-migrated.db
```

PowerShell:

```powershell
$env:SOURCE_DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE"
python scripts/migrate_postgres_to_sqlite.py --sqlite-path .\tenders-migrated.db
```

Use a new destination file, never the live application database. The importer refuses to proceed if any of its 19 target tables already contains rows.

## 2. Data representation

- Integer IDs are preserved, and SQLite autoincrement sequences are advanced to the imported maximum.
- UUID values are stored as text.
- Dates and timestamps are stored as ISO-formatted text.
- PostgreSQL arrays and JSON/JSONB values are serialized as JSON text.
- PostgreSQL numeric values are stored as decimal strings to avoid binary floating-point rounding.
- BYTEA values are copied as SQLite BLOBs.
- Boolean values are stored as SQLite 0/1 integers.
- Foreign-key relationships and row counts are checked before the SQLite transaction is committed.

## 3. Validation and cutover

Review the row counts printed for all 19 tables. The importer checks required source tables and columns, row counts, and SQLite foreign-key integrity. A failure rolls back imported rows.

Before cutover, test authentication, registration, business profiles, company documents, saved tenders, applications, tender alerts, tender dates and documents against the new database. Keep the original PostgreSQL volume and backups untouched until validation is complete. Do not copy over a live SQLite database while services are writing.

This code change does not itself migrate production data or switch production services. Run the migration against the actual PostgreSQL source, review all reported counts, and perform a controlled cutover separately.

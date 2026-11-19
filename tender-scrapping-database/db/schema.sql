-- Shared SQLite schema for the complete application database.
-- Both scraper-api and client-api use /data/tenders.db.
-- PostgreSQL arrays and JSONB are stored as JSON text; UUIDs and timestamps as TEXT.
-- Binary business-document payloads remain BLOBs.

CREATE TABLE IF NOT EXISTS organisations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    email TEXT
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_email_verified INTEGER NOT NULL DEFAULT 0,
    verification_token_hash TEXT,
    verification_token_expires_at TEXT,
    company_name TEXT,
    full_name TEXT
);
CREATE TABLE IF NOT EXISTS pending_registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    verification_token_hash TEXT NOT NULL,
    verification_token_expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    company_name TEXT
);
CREATE TABLE IF NOT EXISTS tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_number TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    organisation_id INTEGER REFERENCES organisations(id) ON DELETE SET NULL,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    tender_type TEXT,
    province TEXT,
    location TEXT,
    published_date TEXT,
    closing_date TEXT,
    special_conditions TEXT,
    tender_url TEXT,
    source TEXT,
    status TEXT DEFAULT 'Open',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tender_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    contact_person TEXT,
    email TEXT,
    telephone TEXT,
    fax_number TEXT
);
CREATE TABLE IF NOT EXISTS briefing_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER NOT NULL UNIQUE REFERENCES tenders(id) ON DELETE CASCADE,
    is_there_a_briefing INTEGER DEFAULT 0,
    is_compulsory INTEGER DEFAULT 0,
    briefing_date_time TEXT,
    briefing_venue TEXT
);
CREATE TABLE IF NOT EXISTS tender_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    document_name TEXT NOT NULL,
    document_type TEXT,
    document_url TEXT NOT NULL UNIQUE,
    date_uploaded TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS scraping_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    tenders_found INTEGER DEFAULT 0,
    tenders_added INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Running',
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS business_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER,
    document_type TEXT,
    filename TEXT,
    content_type TEXT,
    file_data BLOB
);
CREATE TABLE IF NOT EXISTS business_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    business_name TEXT NOT NULL,
    industry TEXT NOT NULL,
    categories TEXT NOT NULL DEFAULT '[]',
    provinces TEXT NOT NULL DEFAULT '[]',
    keywords TEXT NOT NULL DEFAULT '[]',
    min_tender_value TEXT,
    max_tender_value TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    registration_number TEXT,
    vat_number TEXT,
    province TEXT,
    bbbee_level TEXT,
    cidb_grade TEXT,
    csd_number TEXT,
    tender_email TEXT,
    phone TEXT,
    services_offered TEXT,
    business_address TEXT,
    company_description TEXT,
    CHECK (min_tender_value IS NULL OR max_tender_value IS NULL OR CAST(max_tender_value AS NUMERIC) >= CAST(min_tender_value AS NUMERIC))
);
CREATE TABLE IF NOT EXISTS company_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL,
    document_name TEXT NOT NULL,
    document_number TEXT,
    issue_date TEXT,
    expiry_date TEXT,
    status TEXT NOT NULL DEFAULT 'valid',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS alert_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    provinces TEXT NOT NULL DEFAULT '[]',
    categories TEXT NOT NULL DEFAULT '[]',
    organisations TEXT NOT NULL DEFAULT '[]',
    keywords TEXT NOT NULL DEFAULT '[]',
    closing_within_days INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS saved_tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    notes TEXT,
    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, tender_id)
);
CREATE TABLE IF NOT EXISTS tender_applications (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    tender_id INTEGER NOT NULL REFERENCES tenders(id),
    status TEXT NOT NULL CHECK (status IN ('Interested','Preparing','Submitted','Won','Lost')),
    application_deadline TEXT,
    submission_date TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, tender_id)
);
CREATE TABLE IF NOT EXISTS tender_application_history (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES tender_applications(id) ON DELETE CASCADE,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tender_requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    requirement_type TEXT NOT NULL,
    requirement_name TEXT NOT NULL,
    required INTEGER NOT NULL DEFAULT 1,
    minimum_value TEXT,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tender_id, requirement_type, requirement_name)
);
CREATE TABLE IF NOT EXISTS alert_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL REFERENCES alert_preferences(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score >= 0 AND score <= 100),
    reasons TEXT NOT NULL DEFAULT '[]',
    matched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT,
    UNIQUE(alert_id, tender_id)
);
CREATE TABLE IF NOT EXISTS profile_alert_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    profile_id INTEGER NOT NULL,
    tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    score INTEGER NOT NULL CHECK (score >= 0 AND score <= 100),
    reasons TEXT NOT NULL DEFAULT '[]',
    matched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at TEXT,
    UNIQUE(user_id, tender_id)
);

CREATE INDEX IF NOT EXISTS idx_tenders_org ON tenders(organisation_id);
CREATE INDEX IF NOT EXISTS idx_tenders_cat ON tenders(category_id);
CREATE INDEX IF NOT EXISTS idx_tenders_number ON tenders(tender_number);
CREATE INDEX IF NOT EXISTS idx_tenders_closing ON tenders(closing_date);
CREATE INDEX IF NOT EXISTS idx_contacts_tender ON tender_contacts(tender_id);
CREATE INDEX IF NOT EXISTS idx_documents_tender ON tender_documents(tender_id);
CREATE INDEX IF NOT EXISTS idx_logs_source ON scraping_logs(source);
CREATE INDEX IF NOT EXISTS idx_alert_notifications_unread ON alert_notifications(user_id) WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_alert_notifications_user ON alert_notifications(user_id, matched_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_preferences_enabled ON alert_preferences(enabled);
CREATE INDEX IF NOT EXISTS idx_alert_preferences_user ON alert_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_business_profiles_industry ON business_profiles(industry);
CREATE INDEX IF NOT EXISTS idx_business_profiles_user_id ON business_profiles(user_id);
CREATE INDEX IF NOT EXISTS idx_company_documents_user ON company_documents(user_id);
CREATE INDEX IF NOT EXISTS idx_profile_alert_notifications_unread ON profile_alert_notifications(user_id) WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_profile_alert_notifications_user ON profile_alert_notifications(user_id, matched_at DESC);
CREATE INDEX IF NOT EXISTS idx_saved_tenders_user_saved_at ON saved_tenders(user_id, saved_at DESC);
CREATE INDEX IF NOT EXISTS idx_tender_requirements_tender ON tender_requirements(tender_id);
CREATE INDEX IF NOT EXISTS idx_tender_applications_status ON tender_applications(status);
CREATE INDEX IF NOT EXISTS idx_tender_applications_user_id ON tender_applications(user_id);
CREATE INDEX IF NOT EXISTS idx_business_documents_business_id ON business_documents(business_id);
CREATE INDEX IF NOT EXISTS idx_business_documents_document_type ON business_documents(document_type);

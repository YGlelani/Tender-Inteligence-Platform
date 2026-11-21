-- ============================================================
-- SQLite read-query catalogue (used by scraper-api/client-api)
-- ============================================================
-- SQLite does not support PostgreSQL CREATE FUNCTION / RETURNS TABLE.
-- These are SQLite query templates, not stored functions. The Python
-- TenderDB methods bind values with aiosqlite.

-- Named query: list_tenders
SELECT
    t.tender_number, t.title, t.description, t.status, t.province,
    t.closing_date, t.published_date,
    c.telephone AS contact_telephone, c.email AS contact_email,
    o.name AS organisation_name, cat.name AS category_name,
    COALESCE(b.is_there_a_briefing, 0) AS has_briefing, b.briefing_venue,
    (SELECT json_group_array(d.document_url)
     FROM tender_documents d WHERE d.tender_id = t.id) AS document_urls
FROM tenders t
LEFT JOIN organisations o ON o.id = t.organisation_id
LEFT JOIN categories cat ON cat.id = t.category_id
LEFT JOIN tender_contacts c ON c.tender_id = t.id
LEFT JOIN briefing_sessions b ON b.tender_id = t.id
WHERE
    (:status IS NULL OR t.status = :status)
    AND (:province IS NULL OR t.province LIKE '%' || :province || '%')
    AND (:category IS NULL OR cat.name LIKE '%' || :category || '%')
    AND (:organisation IS NULL OR o.name LIKE '%' || :organisation || '%')
    AND (:closing_before IS NULL OR t.closing_date <= :closing_before)
    AND (:closing_after IS NULL OR t.closing_date >= :closing_after)
    AND (
        :keyword IS NULL OR t.title LIKE '%' || :keyword || '%'
        OR t.description LIKE '%' || :keyword || '%'
        OR t.tender_number LIKE '%' || :keyword || '%'
        OR o.name LIKE '%' || :keyword || '%'
        OR cat.name LIKE '%' || :keyword || '%'
    )
ORDER BY CASE WHEN t.closing_date IS NULL THEN 1 ELSE 0 END,
         t.closing_date ASC, t.tender_number
LIMIT :limit OFFSET :offset;

-- Named query: count_tenders_filtered
SELECT COUNT(DISTINCT t.id) AS total
FROM tenders t
LEFT JOIN organisations o ON o.id = t.organisation_id
LEFT JOIN categories cat ON cat.id = t.category_id
WHERE
    (:status IS NULL OR t.status = :status)
    AND (:province IS NULL OR t.province LIKE '%' || :province || '%')
    AND (:category IS NULL OR cat.name LIKE '%' || :category || '%')
    AND (:organisation IS NULL OR o.name LIKE '%' || :organisation || '%')
    AND (:closing_before IS NULL OR t.closing_date <= :closing_before)
    AND (:closing_after IS NULL OR t.closing_date >= :closing_after)
    AND (
        :keyword IS NULL OR t.title LIKE '%' || :keyword || '%'
        OR t.description LIKE '%' || :keyword || '%'
        OR t.tender_number LIKE '%' || :keyword || '%'
        OR o.name LIKE '%' || :keyword || '%'
        OR cat.name LIKE '%' || :keyword || '%'
    );

-- Named query: tender_detail_base
SELECT
    t.*, o.name AS organisation_name, cat.name AS category_name,
    c.contact_person, c.email AS contact_email,
    c.telephone AS contact_telephone, c.fax_number AS contact_fax,
    b.is_there_a_briefing AS has_briefing, b.is_compulsory,
    b.briefing_date_time, b.briefing_venue
FROM tenders t
LEFT JOIN organisations o ON o.id = t.organisation_id
LEFT JOIN categories cat ON cat.id = t.category_id
LEFT JOIN tender_contacts c ON c.tender_id = t.id
LEFT JOIN briefing_sessions b ON b.tender_id = t.id
WHERE t.tender_number = :tender_number;

-- Named query: dashboard_summary
SELECT
    (SELECT COUNT(*) FROM tenders) AS total_tenders,
    (SELECT COUNT(*) FROM tenders WHERE status = 'Open') AS open_tenders,
    (SELECT COUNT(*) FROM tenders
      WHERE closing_date >= datetime('now')
        AND closing_date <= datetime('now', '+7 days')) AS closing_this_week,
    (SELECT COUNT(*) FROM tenders
      WHERE closing_date >= datetime('now')
        AND closing_date <= datetime('now', '+30 days')) AS closing_this_month,
    (SELECT COUNT(*) FROM organisations) AS total_organisations,
    (SELECT COUNT(*) FROM categories) AS total_categories,
    (SELECT COUNT(*) FROM tender_documents) AS total_documents;

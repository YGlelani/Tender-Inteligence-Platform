"""Users who uploaded business documents but have no Business Profile are matched on their documents."""
import sqlite3

DOCUMENTS = {
    "industries": ["Civil engineering"],
    "keywords": ["stormwater drainage"],
    "services": "Stormwater drainage",
    "description": "",
    "provinces": ["Limpopo"],
}


def _without_business_profile(client):
    con = sqlite3.connect(client.db_path)
    con.execute("DELETE FROM business_profiles")
    con.execute(
        "UPDATE tenders SET title = 'Stormwater drainage upgrade', "
        "description = 'Stormwater drainage upgrade' WHERE id = 2"
    )
    con.commit()
    con.close()


def test_documents_alone_give_matches(client):
    _without_business_profile(client)
    client.documents["details"] = dict(DOCUMENTS)

    response = client.get("/matches")

    assert response.status_code == 200
    open_2 = next(item for item in response.json() if item["tender_number"] == "OPEN-2")
    assert "Matches your business documents: stormwater drainage" in open_2["reasons"]


def test_document_provinces_are_a_filter_like_profile_provinces(client):
    _without_business_profile(client)
    client.documents["details"] = {**DOCUMENTS, "provinces": ["Gauteng"]}

    assert client.get("/matches").json() == []


def test_no_profile_and_no_documents_is_still_404(client):
    _without_business_profile(client)

    assert client.get("/matches").status_code == 404


def test_documents_alone_do_not_create_notifications(client):
    _without_business_profile(client)
    client.documents["details"] = dict(DOCUMENTS)

    assert client.get("/notifications").json() == []

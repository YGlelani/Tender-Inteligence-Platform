import psycopg2 # Make sure this is installed: pip install psycopg2-binary

try:
    conn = psycopg2.connect(
        host="129.151.181.87",
        port="5433",
        database="tender_scrapping_db",
        user="tender_scrapping_agent",
        password="tender@scrapping"
    )
    print("Successfully connected to the Oracle database!")
    conn.close()
except Exception as e:
    print(f"Connection failed: {e}")
    
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY client-api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY client-api/app ./app
COPY db ./db

# Run as an unprivileged user; docker-entrypoint.sh drops root after fixing
# permissions on the data volume.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid 10001 --create-home --home-dir /home/app --shell /usr/sbin/nologin app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && chmod 755 /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
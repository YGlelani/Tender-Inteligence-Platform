# Cache API

A read-through caching service that sits in front of `client-api`.

## Purpose

`client-api` talks to Postgres on every request. For a front-end that
frequently fetches the same list of tenders, this is wasteful — the data
only changes every ~30 minutes (when the scraper runs).

`Lelani Cache API` stores responses in Redis and serves them from memory
on subsequent requests. Result: **10–100× faster responses** and much
less DB load.

# ClipForge data collector

The desktop app posts explicit usage events and submitted feedback to your HTTPS API. The server stores them in SQLite. There is no direct database connection or administrator token inside the EXE. The collector exposes the two submission endpoints used by the desktop app and a public health check for hosting.

## Deployment

1. Choose a container host with persistent storage. A domain alone does not run the API.
2. Build the Docker image using `server/` as the build context. Mount a persistent writable volume at `/data` (owned by the container's collector user). Back up this volume.
3. Route HTTPS traffic to port 8000. Configure a custom domain such as `clipforge-api.hichamhr.com` using the DNS records provided by your host. The address is a suggestion, not an existing deployment.
4. Add edge rate limits to POST `/v1/events` and `/v1/feedback`, for example 60 requests/minute/IP, and a 24 KB request limit. These endpoints are intentionally public; installation IDs are not authentication and submitted counts are untrusted. Do not use analytics counts for billing or licensing.
5. Disable request-body logging and minimize IP retention in hosting/proxy logs. Set a read timeout and a connection limit at the proxy. The app restricts payload sizes and fields but does not provide distributed abuse protection.
6. Set `API_URL` in `clipforge_config.py` to the HTTPS base URL, then rebuild ClipForge. Until then, no uploads occur. `CLIPFORGE_API_URL` can override the URL for testing on a machine.

For local server development:

```powershell
py -m venv .server-venv
.\.server-venv\Scripts\python.exe -m pip install -r server\requirements.txt
.\.server-venv\Scripts\python.exe -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

The desktop client accepts HTTPS only. Use local API tests for development, or a TLS endpoint for an end-to-end upload test.

## Receive your data

The desktop app submits data with `POST /v1/events` and `POST /v1/feedback`. There are no admin reporting endpoints. View collected data through private server-side access to the SQLite database; feedback may contain personal information and must not be published. Configure hosting health checks to request `GET /health`, which returns `{"status": "ok"}` when the server is running.

Event IDs make retried submissions idempotent. The metrics count opted-in installations, not all users. App-open time is not active keyboard/mouse time. Recording duration excludes the save phase. Session heartbeats run about once a minute; shutdown is best effort and events can remain queued until a later launch.

## Privacy and retention

Analytics are off by default. Users enable them in More → Privacy & usage statistics. Turning them off deletes queued events, but cannot recall an in-flight request or previously received data. Feedback submission is separate and explicit. The client queues at most 500 submissions; if full, it discards older usage events before rejecting new feedback. It retains unsent feedback until delivery; protect the user's local profile accordingly.

The server records no client IP in its database, but hosting infrastructure sees network addresses. No media, paths, filenames or diagnostic logs are automatically uploaded. Feedback is free text and may contain personal information voluntarily entered by the user.

Before public launch, publish a privacy notice on hichamhr.com with your contact address, host, purposes, retention period and deletion request process. Choose and enforce a retention policy (for example 90 days for raw analytics, with separately agreed feedback retention). The initial server has no automatic expiry job: configure a scheduled database cleanup and backups before accepting production traffic. Removing data from backups also needs a retention policy. Keep storage on a persistent volume; ephemeral hosting loses submissions on redeploy.

This is a single-server collector. For higher traffic, replace SQLite with managed PostgreSQL and use PostHog for retention/funnel dashboards if useful.

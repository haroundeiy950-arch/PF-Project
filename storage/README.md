# Runtime storage

Everything in this folder is generated at runtime and is intentionally ignored
by git (see `../.gitignore`). Only this README is tracked.

| Path | Contents |
| ---- | -------- |
| `sentinel.db` | SQLite database (users, cameras, zones, events, incidents, alerts, recordings, audit log). |
| `snapshots/` | JPEG evidence frames captured for verified threats. Served at `/media/snapshots/...`. |
| `clips/` | Annotated MP4 evidence clips (pre-event + post-event). Served at `/media/clips/...`. |
| `faces/` | Enrolled person photos. Served at `/media/faces/...`. |
| `exports/` | Generated report packages. Served at `/media/exports/...`. |
| `logs/` | Rotating application logs from the AI workers and API. |

The database and logs are **never** mounted over HTTP. Only the four evidence
folders are exposed, and only as static files, so `<img>` and `<video>` tags can
render them without an extra authorization round-trip.

In the default `LIVE_ONLY=true` + `EVIDENCE_ENABLED=true` configuration, the
live dashboard still streams frames in memory, but verified real incidents
write a JPEG to `snapshots/` and a short pre/post-event MP4 to `clips/`.
Set `EVIDENCE_ENABLED=false` (and `RECORDING_ENABLED=false`) for a pure live view
where those folders stay empty.

To start from a clean slate either delete this folder's database file or set
`RESET_DATABASE=true` for a single run.

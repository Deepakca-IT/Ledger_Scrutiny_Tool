# Cloud Feasibility Deep-Dive — LS Tool on Google Cloud + user's Google Drive

*Research date: 09-Jul-2026 (all sources accessed this date). Decision inputs:
data lives in the USER'S Drive via the narrow `drive.file` scope; hybrid model
(local Tally connector + cloud Streamlit app) because Tally ODBC is localhost-only.*

---

## 1. Google Drive API practicalities

### Quotas
- New quota model (projects created on/after 01-May-2026): **1,000,000 quota
  units/min per project, 325,000 units/min per user**. Costs per operation:
  read ≈ 5 units, edit ≈ 50, list ≈ 100, download ≈ 200 units.
  Source: https://developers.google.com/workspace/drive/api/guides/limits
- Our usage per session ≈ a handful of lists + 5–15 downloads + a few uploads
  → well under **1%** of the per-user quota. **Quota is a non-issue** at any
  scale we contemplate (100+ users).

### Throughput / file sizes
- Masters (0.5–5 MB): download in ~1–3 s — fine to fetch per session.
- Transaction CSVs (50–300 MB): Drive API supports resumable upload/download of
  large files, but a 300 MB pull adds tens of seconds to a session start.
  **Mitigations:** (a) connector uploads gzip/Parquet (CSV → Parquet typically
  5–10× smaller, so 300 MB → 30–60 MB), (b) cloud app caches the working copy in
  the Cloud Run instance for the session (Streamlit `@st.cache_data`), so the
  cost is paid once per session, not per rerun.

### `drive.file` scope — the fine print
- Classified **non-sensitive / "recommended"**: *"provides the smallest scope of
  authorization and only require[s] basic OAuth App Verification"* — i.e. **no
  sensitive-scope review, no restricted-scope security assessment.**
  Source: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- It sees ONLY files **created by (or explicitly opened with) the app**. That is
  exactly our model: the connector creates the files; the cloud app reads them.
- ⚠️ **Critical gotcha: access is per-APP.** Files created by one app are NOT
  visible to a different app under `drive.file`. The local connector and the
  cloud app MUST be registered as the **same app (same Google Cloud project /
  OAuth brand)** so they share visibility of the app-created files. This is the
  standard pattern, but it must be **proof-of-concept-tested first** (one
  desktop OAuth client + one web OAuth client under one project, confirm the web
  app lists files the desktop client uploaded). If it fails in practice, the
  fallback is the `drive` (restricted) scope — which triggers the annual
  third-party security assessment — or the user picking their LSTool folder via
  Google Picker once. **This POC is feasibility gate #1.**

### OAuth app verification & tokens
- Sensitive-scope verification ≈ up to 10 days; restricted adds a paid annual
  security assessment — **we avoid both** with `drive.file` (basic verification
  only: brand screen, domain, privacy policy).
  Sources: https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification ,
  https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- While the OAuth consent screen is in **Testing** status, refresh tokens die
  every **7 days** — publish to **In production** before real users, else the
  connector demands re-login weekly. Published refresh tokens last indefinitely
  (revoked if unused ~6 months).
  Sources: https://developers.google.com/identity/protocols/oauth2 ,
  https://www.unipile.com/google-oauth-refresh-token/
- Desktop connector uses the standard **installed-app loopback flow** (browser
  pops, user approves, token cached locally).
  Source: https://developers.google.com/identity/protocols/oauth2/native-app

## 2. Cloud Run + Streamlit fit

- **WebSockets are supported** on Cloud Run (Streamlit is websocket-based).
  Configure **session affinity** (best-effort stickiness) and set **request
  timeout to the 60-min max** — a Streamlit tab's websocket = one long request.
  Sources: https://docs.cloud.google.com/run/docs/triggering/websockets ,
  https://docs.cloud.google.com/run/docs/configuring/session-affinity
- Session affinity is *best effort*; with concurrency set high enough that one
  instance handles all concurrent sessions at small scale, this is a non-issue.
  Multi-instance scale needs sticky-tolerant design (state in Drive/session, not
  instance memory across reconnects).
- **Cold starts:** with scale-to-zero, first user of the day waits ~10–30 s for
  the container (pandas-heavy image). `min-instances=1` eliminates this but
  costs ~$15–25/month for an always-on 1 vCPU / 2 GiB instance. Reasonable
  middle path: scale-to-zero during the pilot; min-instances=1 once paying
  users exist.
- **Memory sizing:** 300 MB CSV → ~1–2 GB in pandas. Use **2 GiB (up to 4 GiB)
  instances**; Parquet + dtype discipline pulls this down a lot.
- **Pricing (Tier-1, beyond free tier):** $0.000024 / vCPU-s, $0.0000025 /
  GiB-s, $0.40 / M requests. **Free tier: 180k vCPU-s + 360k GiB-s + 2M
  requests / month.**
  Sources: https://cloud.google.com/run/pricing , https://cloudchipr.com/blog/cloud-run-pricing
- **Cost bands (1 vCPU / 2 GiB, websocket time = billed time):**
  | Users | Assumed live usage | Est. monthly |
  |---|---|---|
  | 5  | ~2 h/day total  | **₹0 – ₹500** (mostly inside free tier) |
  | 25 | ~8 h/day total  | **₹800 – ₹2,500** |
  | 100| ~30 h/day total + min-instances=1 | **₹4,000 – ₹12,000** |
  Egress is negligible (HTML/JSON to browsers; Drive transfers are Google-internal).
- **Auth:** front the app with Google Sign-In (streamlit-oauth or IAP). The
  signed-in Google identity doubles as the per-seat license key — replaces the
  Tally-serial + license-sheet model for the cloud edition.

## 3. Local connector scope

- Minimum footprint: `pyodbc` (Tally DSN 9400) + `google-auth` +
  `google-api-python-client` + the existing extraction SQL from
  `engines/extract_engine.py` (`_pull_ledger_master`, the DB_Mini transaction
  pull, PAN-from-GSTIN fill). No pandas needed if we stream rows to CSV, but
  keeping pandas (for the existing derive/split logic) is fine — PyInstaller
  one-exe lands ~60–120 MB; still one small file vs today's ~700 MB installer.
- Auth: installed-app loopback flow, refresh token cached in `%APPDATA%`;
  publish consent screen to production to avoid the 7-day token death.
- Update cadence: the connector only changes when the Tally SQL changes —
  rarely. (The whole updater/staging machinery is unnecessary for it; a version
  ping against the cloud app suffices.)
- Support surface that stays local: ODBC DSN present, Tally open, port 9400 —
  same as today's extraction support burden, nothing new.

## 4. Codebase port assessment (as of this repo state)

The 2026 refactors made this far easier than it would have been:
- **`paths.py` is the single path authority** (every engine resolves through
  it), and `get_data_root()` already abstracts WHERE data lives (built for LAN
  Phase A). The cloud port swaps this for a per-user root + a Drive sync layer:
  download-on-open → work on local temp (Cloud Run's writable FS) → upload-on-save.
  `atomic_write_json()` (Phase B) is the single JSON write chokepoint — perfect
  hook for "write locally, then push to Drive".

| Area | Effort | Notes |
|---|---|---|
| `paths.py` → per-user Drive-backed root | **Moderate** | One adapter: hydrate company/FY tree from Drive at session start, push writes back. All engines keep working untouched because they only ever call `paths.*`. |
| JSON configs (grouping, aux, entity, policies, msme master…) | **Trivial** | Small files; already funnel through `paths.atomic_write_json` / `config_path`. |
| CSV reads (fs_engine `load_tb`/master.csv, msme `Conso_MasterData`/`Transactions_*`, clause44, tds) | **Moderate** | Same hydrate-to-temp pattern; big files want Parquet + `st.cache_data`. |
| Extraction (`engines/extract_engine.py`) | **Splits out** | Becomes the local connector (reuse the SQL + derive logic as-is). Consolidation (`consolidate_engine`) can run either side; cloud is simpler. |
| Licensing (`license_engine`, Tally-serial + sheet) | **Rework** | Replaced by Google sign-in identity per seat for the cloud edition. |
| Obsolete in cloud edition | — | `updater.py` + staging, Cython/.pyd pipeline, Inno installer, LAN Phase A/B (shared-folder + locks), `dev_mode.txt` gating. |
| Dual-target cost | **Real but bounded** | Engines are shared; only paths-adapter + auth + packaging differ per target. Keep desktop alive for cloud-averse clients. |

## 5. Risks & showstoppers

1. **`drive.file` cross-client visibility (gate #1)** — must POC before anything
   else. Fallback (full `drive` scope) drags in the restricted-scope security
   assessment: cost + weeks.
2. **Large-file session latency** — 300 MB CSVs over Drive make session starts
   slow. Mitigated by Parquet at the connector + per-session caching; verify
   with one real client dataset (gate #2).
3. **Client-data-in-cloud objections** — some CA clients will refuse any cloud
   processing even with data "in their own Drive" (books transit your server's
   RAM). Keep the desktop edition; position cloud as an option.
4. **Streamlit multi-instance statefulness** — fine at pilot scale (1 instance);
   needs sticky-tolerant session design before ~50+ concurrent users.
5. **Ops responsibility shifts to you** — uptime, monitoring, GCP billing,
   consent-screen upkeep. Small in money, real in attention.
6. **OAuth consent-screen publishing** — do it early; Testing status = 7-day
   refresh tokens = weekly re-login complaints.

## 6. Recommendation

**GO — via a cheap two-gate POC, then an NCE-only pilot.**

- **Week 1 (gates):** (1) one GCP project, desktop client + web client, prove
  connector-uploaded files are visible to the web app under `drive.file`;
  (2) time a real client's transaction file end-to-end (upload → session load)
  in CSV vs Parquet.
- **Pilot (if gates pass):** local connector (reused extract_engine SQL) +
  **NCE module only** on Cloud Run (it's master-file-driven — smallest data,
  cleanest port), Google sign-in for 2–3 friendly users. Desktop product
  continues unchanged in parallel.
- Effort sense-check: connector ≈ small (mostly reuse); paths adapter + NCE
  hosting ≈ the bulk; auth/deploy ≈ small. No irreversible commitments until
  after the pilot.

*Prepared 09-Jul-2026. Sources inline above.*

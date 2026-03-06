# Deferred: Tauri Native Desktop App (Remote Backend First)

## Decision Snapshot

Build a **low-lift desktop proof of concept** using Tauri where the app is a native shell that opens an existing Sift backend URL.

- Keep frontend UI behavior and layout unchanged.
- Do not bundle Python backend in this phase.
- Resolve backend URL from existing config conventions (including `~/.sift.config`).

This is intentionally optimized for speed-to-working-demo.

---

## Why This Approach

### Benefits

1. **Fastest path to native app PoC**
   - No backend sidecar packaging.
   - No Python distribution/signing complexity in app bundle.

2. **No frontend redesign required**
   - Desktop app simply points WebView at backend-served UI.
   - Existing React app remains the single UI source.

3. **Low risk operationally**
   - Reuses backend exactly as deployed today.
   - Keeps all API, auth assumptions, and data behavior in one place.

### Tradeoffs

- Requires backend to be running and reachable.
- Desktop app cannot function offline unless backend exists locally/remotely.
- No major performance gain vs browser expected; value is packaging/UX, not raw speed.

---

## URL Resolution Rules (Desktop App)

Native app should determine target URL in this precedence order:

1. `SIFT_SERVER` env var
2. Config file from `SIFT_CONFIG_PATH` env var (if present)
3. `~/.sift.config` with:

```toml
[server]
url = "http://192.168.1.200:8765"
```

4. Fallback: `http://localhost:8765`

Additional behavior:

- If URL has no scheme, prepend `http://`.
- Optional startup health check (`/hosts` or `/init`) with short timeout.
- If unreachable, show a simple native dialog with retry/edit guidance.

---

## PoC Scope (Phase 1)

1. Tauri app boots and resolves server URL.
2. Main window loads backend URL directly.
3. No visual/UI modifications to current frontend required.
4. Basic error handling for unreachable server.

Out of scope for this phase:

- Bundled backend sidecar.
- Account/session/auth redesign.
- Auto-update/signing pipeline automation.

---

## Expected File/Directory Changes

## Existing files likely touched

- `README.md`
  - Add a short "Desktop App (Tauri PoC)" section with run/build notes.

- `Makefile`
  - Add optional helper targets like `desktop-dev` and `desktop-build`.

- `.gitignore`
  - Ensure desktop build artifacts (for example Rust `target/`) are ignored if needed.

Notes:

- `frontend/src/*` should remain untouched for Option 1.
- `sift/config.py` should remain untouched; desktop logic mirrors its config behavior.

## New files/directories likely created

- `desktop/`
  - Dedicated workspace for native shell to avoid mixing concerns with web frontend.

- `desktop/src-tauri/`
  - Rust/Tauri app configuration and native entrypoint.
  - Implements config resolution, URL normalization, optional health check.

- `desktop/src/`
  - Minimal JS/TS bootstrap for Tauri front-end shell (if needed by template).

- `desktop/tauri.conf.json`
  - App window config, identifiers, packaging settings.

- `desktop/package.json` (or equivalent)
  - Desktop dev/build scripts.

Rationale:

- Clean separation keeps current `frontend/` workflow stable.
- Allows iterative desktop work without destabilizing web build pipeline.

---

## Packaging and Signing Expectations

For local dev/personal testing:

- Unsigned builds are acceptable.
- macOS may show Gatekeeper warning; users can still run via manual trust/open flow.

For broader distribution:

- Add Apple signing + notarization.
- This does **not** slow runtime performance.
- It adds release pipeline overhead (first setup is the largest cost; later releases add predictable minutes plus occasional Apple queue delays).

---

## Future Direction (Deferred)

After remote-backend PoC proves useful, optionally evolve to:

1. Local-first mode (embedded sidecar backend).
2. Dual mode switch (local embedded vs remote backend).
3. Distribution-grade signing/notarization and auto-updates.

This keeps the path open for a one-host default experience later while shipping value early.

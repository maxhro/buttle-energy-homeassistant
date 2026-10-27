# Powermesh Home Assistant Integration

## Current baseline

- Version `0.5.0` (requires service API release `0.2.0`): selected numeric
  sensor readings, optional allowlisted Home Assistant metadata, smoothing and
  bounded offline buffering for powermesh.de.
  Smart-home comparison and improvement potential are **in Entwicklung**,
  not implemented. Do not add analysis, exports, control or data sharing.
- Keep `manifest.json` and `const.py` versions aligned. Website, service and
  integration have independent version lifecycles. Interface documentation
  belongs in the private website/service repositories.
- Public documentation covers setup, sensor selection, status and privacy,
  never endpoints, headers, payload formats or error codes. State that
  powermesh.de terms apply. Do not publish credentials, archives, caches,
  virtual environments or test runtime data.
- Data is pseudonymous, not anonymous. Registration is not consent to sell or
  share household data. Retain explicit sensor selection, HTTPS/TLS, bounded
  buffering, confirmed-storage removal and visible loss/error reporting.
  Pending values must not be silently reassigned on a credential change.
  Do not reinterpret incompatible stored data or delete user data automatically.

## Setup paths and trust boundary

- Setup offers an existing personal API key or a new account with an
  operator-issued invitation (24-hour, single-use bearer authorization, not
  proof of an official client). Existing accounts are rejected by the service.
- Privacy, terms and storage consent are separate explicit confirmations with
  the current consent versions. Entities and smoothing are chosen before the
  single registration request; the issued key is stored at once. Never retry
  registration automatically, never retrieve keys another way; ambiguous
  outcomes abort with a warning that the invitation may be consumed.
- Email, password and invitation are sent only via HTTPS to the fixed service and
  never persisted in entries, storage, logs, diagnostics or issues.
- Website email confirmation and TOTP enrollment must finish within 168 hours.
  Show the deadline immediately and keep a persistent repair issue until the
  service reports `setup_required: false`; expired accounts stay visible as an
  auth problem with no automatic re-registration or key issuance. The service
  rejects expired keys with its ordinary auth error, so expiry is derived from the
  remembered server deadline; do not invent dedicated error codes.
- A registration response with a valid key but malformed account status keeps
  the key and shows a persistent protocol-error issue without a fabricated
  deadline until the service reports the account status.
- The current implementation is the project baseline. Describe current behavior
  and constraints, not implementation history or earlier project states.

## Checks

- Isolated Python environment: `pytest -q` and
  `python -m compileall -q custom_components`. Use synthetic data and mocked
  transport; never probe production or send real household data.
- Package checks: `node --test tests/package.test.mjs`.
- PowerShell 7: `pwsh -NoProfile -File ./build-package.ps1 -DryRun`;
  `-BuildPackage` creates a local manual-install ZIP without overwriting output.
  Packaging never publishes a release or connects to Home Assistant.
- HACS and hassfest jobs in `.github/workflows/validate.yml` are required before
  merge/release. A skipped or unavailable validator is not proof of acceptance.
  Keep private cross-project compatibility checks aligned.

## Operations

- Deployment, releases, pushes and live Home Assistant installation require
  separate authorization. A working service and matching website-issued key
  are prerequisites for installation acceptance, not assumptions.
- Controlled acceptance covers consent/access, sensor selection, smoothing,
  buffering, reconnect, deletion and diagnostics using synthetic data.
  Preserve user changes; stop owned test helpers and clean temporary files.

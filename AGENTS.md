# Powermesh Home Assistant Integration

## Approved implementation — 2026-10-26

- The 0.1.0 prototype is approved to use the fixed HTTPS readings service and
  optional allow-listed Home Assistant metadata. This integration only stores
  selected readings; comparison and improvement potential remain in development.
- Keep the version in manifest.json and const.py aligned. Web, service and
  integration lifecycles are independent. Do not publish, deploy or change a live
  Home Assistant installation without separate approval.
- This is a fresh-install baseline. Existing entries are not automatically
  upgraded. Legacy stored readings are retained and block upload when their format
  is incompatible; never reinterpret them as new readings.
- Existing CI checks HACS, hassfest, mocked Python tests, compileall and the local
  package tests. For this implementation, Python tests, compileall, Node package
  tests and the PowerShell package dry-run passed locally. The actual HACS
  (`hacs/action`) and Home Assistant hassfest validators were not run locally:
  their executables are unavailable and Docker is unavailable. The `hacs` and
  `hassfest` jobs in `.github/workflows/validate.yml` remain required CI gates
  before merge or release. PowerShell 7 package creation remains manual and local
  only.
- A working private service and matching account-issued credentials must be
  confirmed before installation acceptance. Website key issuance must align with
  the canonical service key before the integration can be used. No live-service
  test is included.
- Public documentation must describe user setup and privacy without publishing
  interface details. Never commit archives, credentials, caches, virtual
  environments or test runtime data.

## Next steps, only after approval

- Coordinate backend readiness and credential issuance before claiming a working
  production service. Do not probe production from tests.
- Complete Windows package checks and a controlled manual fresh installation in
  Home Assistant only after explicit authorization.
- Verify consent/access setup, sensor selection, buffering, reconnect/deletion
  behavior and diagnostics without real household data or production probing.
- Deliberately handle old entries/buffers with the operator; never migrate or delete
  them automatically. Publish a release only after explicit authorization and checks.

## Checks and boundaries

- Use the existing isolated test environment: `pytest -q` and
  `python -m compileall -q custom_components`. Tests use synthetic data and mocked
  network boundaries.
- Package checks: `node --test tests/package.test.mjs`.
- PowerShell 7: `pwsh -NoProfile -File ./build-package.ps1 -DryRun`, then
  `-BuildPackage` for a local manual-install ZIP; existing outputs are not overwritten.
- Preserve user changes, secure TLS, application-level storage confirmations and
  visible buffer loss/error reporting. Do not add analysis, exports, device control
  or data sharing.
- Comparison and improvement potential remain in development. Data is pseudonymous,
  not anonymous; registration is not consent to sell household data.

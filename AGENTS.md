# Powermesh Home Assistant Integration

## Paused handoff — 2026-10-26

- Implementation is paused at the user's request. Await the next explicit task;
  do not deploy, publish releases or modify Home Assistant installations on your own.
- Fresh-install prototype version is 0.1.0. Keep manifest.json and const.py versions
  aligned. Website, service and integration version lifecycles remain independent.
  Never overwrite existing Git tags/releases or silently downgrade HACS installs.
- MQTT integration, setup/options, bounded persistent offline buffering, diagnostics,
  translations and PowerShell 7 manual-install package builder are prepared.
  The package does not install remotely, remove entries or delete existing buffers.
- Local Python tests: 50 passed, one opt-in live test skipped. Both package tests
  passed; the private workspace's required compatibility gate passed. Live-service,
  Windows and actual Home Assistant installation acceptance remain open.
- PR CI requires aiomqtt 2.5.0 to satisfy current Home Assistant constraints;
  keep the manifest and test dependency pins aligned, never restore 2.4.0.
- A verified ZIP exists locally in ignored dist. Never commit archives, .env,
  credentials, caches, virtual environments or test runtime data.
- Public documentation must not describe private interface topics, envelopes,
  headers, payloads, error codes or protocol examples. Consult the private service
  repository for the contract; keep handoff/release notes free of those details.

## Next steps, only after approval

- The backend still needs a suitable persistent operating environment; current
  PHP webhosting alone is insufficient. Do not imply a usable production service.
- Coordinate private backend readiness, guarded synthetic real-service testing,
  Windows package tests and a controlled manual fresh installation in Home Assistant.
- Verify consent/access setup, sensor selection, buffering, reconnect/deletion
  behavior and diagnostics without real household data or production probing.
- Deliberately handle old entries/buffers with the operator; never migrate or delete
  them automatically. Publish a release only after explicit authorization and checks.

## Checks and boundaries

- Use the existing isolated test environment: `pytest -q` and
  `python -m compileall -q custom_components`. Tests use synthetic data and mocked
  network boundaries. Live tests require explicit isolated-loopback opt-in.
- Package checks: `node --test tests/package.test.mjs`.
- PowerShell 7: `pwsh -NoProfile -File ./build-package.ps1 -DryRun`, then
  `-BuildPackage` for a local manual-install ZIP; existing outputs are not overwritten.
- Preserve user changes, secure TLS, honest storage confirmations and visible buffer
  loss/error reporting. Do not add analysis, exports, device control or data sharing.
- Comparison and improvement potential remain in development. Data is pseudonymous,
  not anonymous; registration is not consent to sell household data.

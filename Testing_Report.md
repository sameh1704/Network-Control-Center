# تقرير الاختبارات — Network Control Center

## Automated (simulated)
- Backend pytest: 20 passed (validation + API).
- Flutter: not executed locally (no Flutter SDK in this environment); workflow provided.

## Simulated coverage
- Host validation (private only).
- Credential encryption roundtrip.
- Device CRUD and persistence (SQLite temp file).
- ESXi VM discovery (mocked).
- VM power_on (mocked).
- reboot_guest requires VMware Tools (mocked).
- FortiGate reboot disabled by default.
- Audit log.
- Diagnostics.
- Test connection endpoint.

## Live hardware
- BLOCKED: no real ESXi/FortiGate credentials or network access in this environment.

## Notes
- pyvmomi version installed: 9.1.1 (requirements allow 8.0–9.x).

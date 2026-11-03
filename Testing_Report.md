# تقرير الاختبارات — Network Control Center

## Automated (simulated)
- Backend pytest: 24 passed (validation + API).
  - PASS: health auth, device CRUD, public host rejection, FortiGate token validation
  - PASS: ESXi VM discovery (mocked), including suspended state mapping
  - PASS: VM power_on (mocked) returns 200, waits for task completion, audit 'ok'
  - PASS: power_on rejected 409 when VM poweredOn
  - PASS: duplicate simultaneous command rejected 409 + audit 'conflict'
  - PASS: power_on task timeout 504 + audit 'timeout'
  - PASS: power_on VMware fault 502 + audit 'failed', no secrets logged
  - PASS: reboot_guest requires VMware Tools (mocked)
  - PASS: FortiGate reboot disabled by default, audit log, diagnostics, test connection
- Flutter: BLOCKED — no Flutter SDK in this environment; `flutter analyze`, widget tests, layout tests at 320/360/393/480 logical pixels, and release APK build could not be executed locally.
  - Widget test suite written at mobile/test/vm_card_test.dart (unexecuted).

## Simulated coverage
- Host validation (private only).
- Credential encryption roundtrip.
- Device CRUD and persistence (SQLite temp file).
- ESXi VM discovery (mocked): on / off / suspended / unknown.
- VM power_on (mocked): real pyVmomi PowerOnVM_Task path, task wait, duplicate guard, faults, timeouts.
- reboot_guest requires VMware Tools (mocked).
- FortiGate reboot disabled by default.
- Audit log (action/target/result/details, no secrets).
- Diagnostics.
- Test connection endpoint.

## Live hardware
- BLOCKED: no real ESXi/FortiGate credentials or network access in this environment.
- Do not issue real production VM power commands during testing.

## Notes
- pyvmomi version installed: 9.1.1 (requirements allow 8.0–9.x).
- Existing APK: F:\NCC\Network_Control_Center.apk (not rebuilt; Flutter SDK unavailable).
- Backups preserved: controller/main.py.pre-poweron.bak, mobile/lib/main.dart.pre-ui.bak.

# قائمة أمان — Network Control Center

- [ ] NCC_API_KEY (32+ chars) not in source.
- [ ] NCC_ENCRYPTION_KEY stored securely, not in repo.
- [ ] SQLite DB permissions restricted.
- [ ] Backend bound to 127.0.0.1 behind HTTPS reverse proxy.
- [ ] VPN-only access enforced.
- [ ] No ESXi/FortiGate/SSH exposed to internet.
- [ ] TLS verification enabled (CA installed).
- [ ] FortiGate reboot disabled until verified.
- [ ] ESXi host reboot disabled.
- [ ] Audit log enabled.
- [ ] Backups configured.
- [ ] Release APK signed with private key (not debug).
- [ ] No secrets in GitHub repo.

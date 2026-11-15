# 0047. Split milestone 6 into seven features

- Status: Accepted
- Date: 2026-11-15

## Context
Milestone 6, Operations (design doc "Implementation plan"), covers encrypted backups and restore, services, the tunnel, SMTP, a wall-QR page, a setup guide and all deployment testing. It was planned for the gym PC; decision 0046 moved hosting to a dedicated Linux server that staff reach over the web from any computer. That adds remote access to the admin app, and the server isn't ready yet, so the work is split by what can be built on the dev PC now and what needs the server.

## Options
- **One big feature**: too large to review, and half of it would wait for the server.
- **Features by area, the server-free ones first**: work continues while the machine is set up, and each piece is one reviewable PR.

## Decision
Seven features, in this order:

**Built now, on the dev PC:**
1. **Database encryption (SQLCipher)**: the whole file encrypted with a key from `.env` (decision 0005), and a one-time command that converts an existing plain database. Whether dev on Windows keeps plain SQLite is decided in that feature.
2. **Encrypted backups and restore**, with the dashboard's backup card: a consistent copy at startup and at 22:00 from the existing hourly job (decision 0045), an encrypted zip including `reports/`, 30 daily backups plus one per month, written to a folder; the off-site copy (e.g. `rclone`) is set up on the server. How restore runs is decided in that feature.
3. **Hardening**: security headers and a content security policy on both apps, a refusal to start on `0.0.0.0`, absolute paths for the database and `reports/` in prod, the owner PIN reset command.
4. **Wall-QR page**: a printable page with the check-in QR; the public address becomes a setting.

**Needs the server and a domain on Cloudflare:**
5. **Server setup**: systemd services for both apps and `cloudflared`, a deploy routine (migrations, frontend build, restart), the named tunnel for the public app, real SMTP, and a setup guide (LUKS, updates, secrets).
6. **Remote access to the admin app**: its own hostname through the tunnel, a Cloudflare Access gate, the allowed host name, the `Secure` staff cookie, the client IP from `CF-Connecting-IP` (staff auth, a protected area).
7. **Launch checks**: edge rate and body-size limits, the cookie on real phones, the report email in Gmail and Outlook, a full restore test, the two-week pilot.

Encryption comes before backups because copying and restoring an encrypted database works differently. Hardening comes before anything is exposed.

## Consequences
- Features 1–4 can be built while the server is being set up.
- Before feature 5: which domain to buy, and whose Cloudflare account owns it.
- The admin app on phones stays out of scope (decision 0046).

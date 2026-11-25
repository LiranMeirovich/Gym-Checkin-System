# 0053. Server setup: Ubuntu 24.04 with LUKS, a domain on Cloudflare, cloudflared in Compose, off-site backups to the gym's Google Drive

- Status: Accepted
- Date: 2026-11-25

## Context
Server setup (milestone 6, feature 6; decisions 0046, 0047, 0052) starts on the dedicated machine. It turned out to run Ubuntu 20.04, whose free security updates ended in April 2025, on a disk without encryption (LVM, no LUKS), although decision 0046 requires LUKS. LUKS can't be added to the running system disk afterwards. Still open from 0047 and 0052: whether a domain is needed at all, where `cloudflared` runs, where the off-site backup copy goes, and what the deploy routine looks like.

## Options
- **OS**: reinstall Ubuntu 24.04 LTS with LUKS (wipes the machine, which holds no real data yet), or keep 20.04 with Ubuntu Pro's free security updates and no disk encryption (against 0046).
- **Address**: serve the public app on the server's IP, or a domain on Cloudflare through a named tunnel. By IP needs an open inbound port, a fixed public IP, and an https certificate for a bare IP (barely available, short-lived); the printed wall QR (0051) breaks when the IP changes, and Cloudflare Tunnel and Access (feature 7) need a domain. Cloudflare's quick tunnel gives a random address that changes on every restart.
- **cloudflared**: a third service in `compose.yaml` (digest-pinned image, same restart policy and logs as the apps, tunnel token in `.env`), or Cloudflare's apt package as its own systemd unit.
- **Off-site backups**: `rclone` to the gym's Google Drive, the developer's own Google Drive, or Backblaze B2.
- **Deploy routine**: a script, or the commands listed in the guide.

## Decision
- **Reinstall Ubuntu 24.04 LTS with LUKS** ("Use LVM and encryption" in the installer) before anything else goes on the machine. It fixes the unsupported OS and the missing disk encryption in one step, while there's nothing to lose.
- **A domain on Cloudflare is required**; the public app is not served by IP. Customers never type the address (they scan the QR), but https for the `Secure` cookie, the outbound-only tunnel (no open ports, which also matters in the server room), a QR that survives moving the machine, and Cloudflare Access for the admin app all need one. One domain covers both apps (e.g. `checkin.` and `admin.` subdomains). Buying it is the developer's next step; the tunnel waits for it.
- **`cloudflared` is a third Compose service** on the host network, so everything runs and restarts the same way and one `docker compose` manages it.
- **Off-site: `rclone` copies `GYM_BACKUPS_DIR` nightly to a Google Drive owned by the gym's Google account** (the account that also sends the report). The zips are already AES-encrypted (0049), so Google holds only ciphertext.
- **Deploy: `scripts/deploy.sh`** runs `git pull`, build, stop, migrate, start (0052's routine) so no step is skipped or reordered.

## Consequences
- The machine is wiped: the developer backs up anything personal first, keeps the LUKS passphrase off the machine with the other keys, and sets up git, the SSH key and Claude Code again afterwards.
- A yearly domain cost (about $10 for a `.com`).
- The tunnel token is a new secret in `.env`; the guide lists it with the keys to keep off the machine.
- A new `scripts/` folder in the repo.
- The off-site copy depends on the gym's Google account staying under the gym's control; rclone's Drive token is another secret on the server.
- The design doc's Architecture and Security sections (still the gym PC, BitLocker, Windows services) are updated in this feature.

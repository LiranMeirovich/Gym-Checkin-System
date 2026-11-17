# 0046. Host the system on a dedicated Linux server

- Status: Accepted (plain or under Docker settled by [0052](0052-run-the-apps-in-docker.md): Docker Compose)
- Date: 2026-11-15

## Context
The design doc planned for both apps to run on the gym's front-desk Windows PC, with the public app exposed through a Cloudflare Tunnel and the admin app reachable only on that PC (`127.0.0.1:8000`). Hosting was left open because a free server might replace the PC (design doc, Open questions: "Hosting"). Milestone 6 (services, tunnel, SMTP, backups, deployment testing) can't be planned until this is settled.

## Options
- **The gym PC (Windows)**: the original plan. No extra hardware, and the admin app stays on the machine staff use. But the system depends on a shared desk PC, and SQLCipher is hard to install on Windows (decision 0005).
- **The village's shared server**: free, but who controls the machine and who else can reach the data were still unknown.
- **A paid VPS** (about ₪200/year): managed hardware, but a yearly cost and customer health data on a third party's disks.
- **A dedicated Linux machine of the developer's**: runs on its own first, then moves to the town's shared server room.

## Decision
A dedicated Linux machine, set up by the developer, which will later move to the server room in town where other servers sit. The gym's desk PC becomes only a client: staff use the admin app in its browser over the web, and customers' phones use the public app as before.

The manager can use the admin app from anywhere, on any computer (the desk PC, home), not only at the gym. Phones aren't supported for the admin app for now: the manager will mostly use a PC, and the staff screens are built for a wide screen. If phone use turns out to be needed, it's a later layout change.

## Consequences
- **The admin app is no longer local-only.** Until now it was protected by being reachable only on the PC it ran on (`127.0.0.1`, the host guard in `app/admin/main.py`, a staff cookie without `Secure`). Reaching it from the desk over the web needs a real hostname with https, `ALLOWED_HOSTS` and the `Secure` flag on the `gym_staff` cookie, and an access gate in front of it, since a staff PIN alone would then face the whole internet. The design doc suggests Cloudflare Access; the choice is made in its own milestone 6 feature (staff auth, a protected area).
- **Both apps still bind to `127.0.0.1` on the server**; the Cloudflare Tunnel connects to them, so no ports are opened in the server room.
- **SQLCipher installs cleanly on Linux** (decision 0005). Development stays on Windows with plain SQLite unless a Windows driver works too.
- **Services are systemd units** (plain or under Docker, still to decide), not Windows services. Disk encryption is LUKS, set up when Linux is installed, not BitLocker.
- **Backups need a new off-site copy**: the Google Drive for desktop folder doesn't exist on Linux (e.g. `rclone` to a cloud drive). Off-site matters more on a machine in a shared room.
- **Who can reach the machine in the server room** (physical and network access) matters as much as the encryption (decision 0005); confirm it before moving it there.
- The design doc's Architecture, Security and backups, and Implementation plan sections still describe the gym PC and need updating.

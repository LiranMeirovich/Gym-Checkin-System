# 0051. The wall QR is fixed to the public hostname, not a setting

- Status: Accepted
- Date: 2026-11-17

## Context
Milestone 6's fourth feature (decision 0047) is a printable page with the check-in QR, and 0047 said "the public address becomes a setting". Since hardening (decision 0050), the public address already exists: `GYM_PUBLIC_HOSTNAME`, deployment config required in prod, and the public app refuses any other `Host`. The QR is printed once and mounted at the entrance (design doc: "The wall QR"), so it should always open the same link.

## Options
- **A manager-editable setting** (as 0047 said): a second copy of the address that can drift from `GYM_PUBLIC_HOSTNAME`; a printed QR would then open a host the public app refuses, and every scan would fail.
- **Move the hostname into the settings table**: one value, but the public app's host check would read the database on every request, and hardening changes.
- **Build the QR from `GYM_PUBLIC_HOSTNAME`**: one source of truth, nothing to edit; changing the domain means changing the server's config (and the tunnel) anyway.

## Decision
The wall QR always encodes `https://<GYM_PUBLIC_HOSTNAME>/c`. There is no setting for it.
- `app/core/wall_qr.py` builds the address and the QR (`segno`, pure Python, no dependencies; error correction Q, the standard quiet zone) as an SVG `data:` URL, which the CSP already allows for images.
- `GET /api/wall-qr` (`settings.edit`: owner and managers) returns `{url, qr_image}`, both null when no hostname is set (dev only). Reading it isn't logged.
- The admin app's `/settings/wall-qr` page, opened from the Settings screen without the staff header, shows the logo or name, the QR, one line of text and the address, with a Print button; printing shows only the poster, sized for A4. No `@page` rule, since the admin build's one stylesheet would apply it to every screen.

## Consequences
- The QR and the public app's host check can't disagree.
- A new domain means printing a new QR; the address is printed under it so staff can tell which one is on the wall.
- The poster's wording, size and colours aren't editable.
- Scanning the printed QR with a real iPhone and Android phone waits for the launch checks (decision 0030).

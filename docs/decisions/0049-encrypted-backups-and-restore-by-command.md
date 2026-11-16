# 0049. Encrypted backups from the scheduled job; restore by a command on the server

- Status: Accepted
- Date: 2026-11-16

## Context
Milestone 6, feature 2 (decision 0047): encrypted backups and restore, with the dashboard's backup card. The design doc asks for a consistent copy at startup and every day at 22:00, an AES-256 zip, the last 30 backups plus one per month, a card that turns red after 2 days without a backup, and restore as a menu action. Since then the system moved to a Linux server reached over the web (decision 0046), and the database is encrypted with SQLCipher (decision 0048). Decision 0047 left how restore runs to this feature.

## Options
**Restore**
- **A menu action in the admin app** (the design doc): upload a backup and its password, and the app swaps the database. But both apps (two processes) hold the file open, so swapping it while they run risks a broken or half-read database; it would need a maintenance mode across both. It would also accept a database file uploaded over the internet.
- **A command on the server, both apps stopped**, like `app.encrypt_database`: no running app to coordinate with, and whoever runs the server (not the manager) is the one who restores.

**Encryption**
- **`pyzipper`** (AES-256 zip, WinZip AE-2): 7-Zip opens it; small. Zip's key stretching is weak (PBKDF2-SHA1, 1,000 rounds).
- **`py7zr`** (7z, AES-256, stronger stretching): maintained, but more dependencies.
- **Our own format on `cryptography`**: strongest, but no ordinary tool opens it.

**Where the folder and password live**
- **Env config** (`GYM_*`), like the database key.
- **The settings table**, editable by managers (the design doc's data model listed "backup folder").

**The record of backups**
- **A table** of backup runs.
- **The backups folder itself**: the file names are the record.

## Decision
- **Restore is a command:** `python -m app.restore_backup <file>`, both apps stopped. It asks for the password without showing it, and checks everything before touching anything: the password, every file's checksum, that the code knows the backup's migration, and that the database opens with this install's `GYM_DATABASE_KEY` and passes SQLite's and SQLCipher's integrity checks. It refuses while an app has the database open. The current database and `reports/` are renamed to `….before-restore-<time>`, never deleted. A backup at an older migration is restored with a reminder to run `alembic upgrade head`.
- **`pyzipper`, AES-256,** with `GYM_BACKUP_PASSWORD` required to be at least 32 random characters. A random password that long can't be guessed whatever the stretching, so the weak stretching doesn't matter, and the files open in 7-Zip in an emergency.
- **Env config:** `GYM_BACKUPS_DIR` (default `backups/`) and `GYM_BACKUP_PASSWORD` (required in prod; dev without it makes no backups). The folder is a fact about the server that the off-site copy reads from, not something the manager edits.
- **The folder is the record:** `gym-backup-<local date and time to the second>.zip`. No table, so restoring an older backup can't roll back the record of newer ones. Each zip holds the database (copied with SQLite's backup API through keyed connections, so it stays encrypted with the database key), `reports/` and a manifest (when it was made, its migration). It's written as `.partial`, reopened and checked, then renamed.
- **When:** the admin app's hourly job thread (decision 0045) makes one at startup and one in the first run at or after 22:00 local time, then keeps the newest backup of each of the 30 most recent days that have one, plus the newest of each calendar month, for good. By day, not "the 30 newest", so an app restarted over and over (a backup at each start) can't push out the days before. A backup dated after "now" (a clock that was ahead) doesn't count as the last one. The report and the backup are tried separately, so one failing never stops the other.
- **The dashboard's card:** `GET /api/backups/latest` (`configured`, `last_backup_at` in local time, `overdue`), under the existing `backups.manage` permission (owner and managers). Overdue (no backup, or none for 2 days) is decided on the server.

## Consequences
- **A restore needs both the backup password and `GYM_DATABASE_KEY`.** Both go on the list of keys kept off the machine.
- **The design doc's "menu action" restore and "backup folder" setting are replaced** by the command and `GYM_BACKUPS_DIR`.
- **Prod refuses to start without `GYM_BACKUP_PASSWORD`.**
- **The card reads file names, not the zips:** it shows that a backup file exists, not that it would restore. Each backup is checked when it's made; a full restore test belongs in the launch checks (decision 0047, feature 7).
- **The off-site copy (e.g. `rclone`) is still to set up**, in server setup (feature 5).
- **The in-use check isn't airtight:** an app started between the check and the swap could open the old file, so "both apps stopped" stays the rule.
- **The `.before-restore-` copies and a crashed backup's leftovers** (`.partial`, `.backup-*`) stay until removed by hand.

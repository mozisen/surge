# Database Guidelines

> Database patterns and conventions for this project.

---

## Overview

<!--
Document your project's database conventions here.

Questions to answer:
- What ORM/query library do you use?
- How are migrations managed?
- What are the naming conventions for tables/columns?
- How do you handle transactions?
-->

(To be filled by the team)

---

## Query Patterns

<!-- How should queries be written? Batch operations? -->

(To be filled by the team)

---

## Migrations

<!-- How to create and run migrations -->

(To be filled by the team)

---

## Naming Conventions

<!-- Table names, column names, index names -->

(To be filled by the team)

---

## Common Mistakes

<!-- Database-related mistakes your team has made -->

(To be filled by the team)

## Notifications (panel)

- `notifications` is a send queue, not a history: `send_pending()` deletes each row after the delivery attempt, and rows left `sending` by a dead process are deleted without resending. Never add UI or API that reads it as a log; backup restore empties it.
- `settings['notifications']` is normalized by `monitor.normalize()` (defaults, legacy `telegram_token`/`telegram_chat` migration). Writes go through `monitor.write()`, which also stores the legacy keys so an older panel keeps administrator alerts after a rollback.
- Telegram bind codes: store only the SHA-256 (`platform_tg.code_hash`), 24-hour expiry, one-time; never log or audit the code. One chat per platform user (`platform_tg` primary key) and one user per chat (partial unique index); the row cascades with `platform_users`.
- The user bot runs inside the flock-elected monitor worker; advance `bot_offset` before handling an update so a crash never replays `/bind`.

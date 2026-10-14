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

## Port forwards (panel / agent / script)

- One contract in `vaio/common.py`: `validate_forward_rule` (same constraints as the script's `_fwd_validate`; nftables = TCP+UDP, listen 0.0.0.0, IPv4 target), `validate_forward_task` (exactly one op), `sanitize_forwards` (snapshot rows; malformed rows are dropped, at most 500).
- The panel never trusts a client-supplied base: `POST /api/nodes/<id>/forwards` takes `{op, id?, rule?}` and builds `base` from the node's last snapshot inside `node_task` (request built after `check`). The script rejects with `rule_changed` when the node's rule differs, so script-menu or nft.sh edits are never overwritten.
- Agent: `forward_apply` goes through `Bridge` like `platform_apply` (journal, unknown never replayed, result lookup) and calls `ScriptAPI.invalidate()` so the next snapshot carries the new rules; forwards come from the script inventory (cached 60 s), not from db.json.

## User authority on adopted servers

- Adopted servers are platform-managed. `platform_users.auto_authority()` (called from the agent poll and the monitor scan) queues `set_authority platform` for adopted, online, non-maintenance nodes that report `authority_version=1`, are still script-managed and hold no script users; request keys `auto-authority:*` mark these tasks, and a failed one is retried only after `AUTO_AUTHORITY_RETRY` (1 h). Nodes with script users wait for the operator (detail-page notice → `authorityDialog`, name confirmation).
- The detail page has no user-management block; tests that need a script-managed node must give it a script user.

## Relay lines

- `vaio/relays.py` owns `relay_lines` (hops JSON: node, stored forward rule, `forward_id`, `task_id`, status). Each hop is an ordinary `forward_apply` task whose `request_key` is `relay:<line>:<index>:<add|delete>:<nonce>`; `relays.task_finished()` (called from the agent result handler, which now keeps the `rule` result field) writes the outcome back. The line state is derived (creating / active / partial / removing), never stored.
- Creation is all-or-nothing inside one transaction: every check (servers distinct, relay nodes forward-capable and idle, public address for the next hop, port conflicts from snapshots, landing instance present) runs before any task row or link change. Landing membership reuses `platform_users.add_link` / `member_op`.
- Deleting always asks the node by the recorded `forward_id` (snapshots lag behind a just-created rule); a failure whose message says the rule no longer exists counts as removed. Node public addresses come from the agent's background watcher (`snapshot.addresses`, global unicast only after sanitizing).

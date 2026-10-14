# Component Guidelines

> How UI pieces are built in the Vaio Panel front end (`platform/web/`).

---

## Overview

The panel is a single vanilla-JS file (`platform/web/app.js`) plus one stylesheet (`platform/web/style.css`). There is no framework and no build step. Views and dialogs are functions that build an HTML template string and assign it, then attach handlers by element id with `$('#id')`. UI text is Chinese; the visual style is black and white minimal (see `CLAUDE.md`).

---

## Component Structure

- A view or dialog is one function: render markup, then wire handlers, then call a local `update…()` that applies hidden/disabled/required state.
- Dialogs go through `modal(title, body, wide = false, extraClass = '')` (`app.js`). It replaces the dialog's innerHTML, so listeners attached to the previous body are dropped with it; re-attach on every render.
- A dialog that needs its own layout passes `extraClass` (for example `install`) and scopes all CSS to `dialog.<class>`. Do not change the base `dialog`, `.modal-body`, `.modal-foot` or `.wide` rules for one dialog.

### Convention: element ids are the test contract

**What**: `tests/install-form.cjs` runs the slice of `app.js` from `installPortCandidate` up to `editUser` inside `node:vm`, with every element stubbed by id. Moving markup around is safe; renaming or removing an id used by the handlers is not.

**Why**: The vm harness has no DOM. It only knows the ids listed in its stub array, so a renamed id fails as `undefined`, and a new `$('#id')` lookup needs a new stub.

**Example**:
```js
// app.js: new element queried in updateFields()
$('#install-advanced').hidden = groups.every(id => $('#' + id).hidden);
// tests/install-form.cjs: add 'install-advanced' to the stub id list
```

---

## Styling Patterns

- Greys only. Tokens on `:root` in `style.css`: `--ink #000`, `--ink-2 #333`, `--muted #6b6b6b`, `--line #d9d9d9`, `--line-soft #ececec`, `--canvas #f5f5f5`, `--surface #fff`. Legacy names (`--accent`, `--accent-soft`, `--danger`, `--bg`, `--nav`, …) are aliases kept so old rules resolve; do not add new colours (`#8c8c8c`/`#b3b3b3` exist only for placeholder/hover/chart baseline).
- Radius by hierarchy: `--r-badge` 3px, `--r-control` 6px, `--r-panel` 8px, `--r-dialog` 12px. Panels have no shadow; only `dialog`, `#toast` and the filter menu popover (`.filter-pop`, a floating layer) do.
- System font stack only (no webfonts: the panel is self-hosted and must not call third parties). Numbers use the global `tabular-nums`; `.mono` is for machine strings (ports, service names, commands, filenames, event keys), not for metrics or timestamps.
- Numeric table columns get `class="num"` on both `th` and `td` (right-aligned).
- Groups are a 13px/600 heading over a 1px `--line` top divider. Use `fieldset` for semantics with `border: 0; padding: 0`, not boxed sets.
- An inline action next to an input ("生成") uses `.input-action` (`grid-template-columns: 1fr auto`) and keeps the button's id.
- A long dialog keeps the head and `.modal-foot` fixed and scrolls only the middle (`.install-scroll`), so the primary button is always visible. A `.modal-foot` that is the last child gets the top rule and grey band via `dialog:not(.install)`; `dialog.install` styles its own footer.
- Narrow screens use the 1150px and 760px breakpoints; check 375px for horizontal scroll. Under `(pointer: coarse)` every control, `summary`, checkbox label and text link is at least 44px high.

### Convention: monochrome status badges

**What**: `badge(status)` returns `<span class="badge STATUS">文字</span>` and nothing else; the state mark is a CSS `::before`:

| Classes | Mark |
|---|---|
| `online`, `running` | solid dot, weight 600 |
| `succeeded`, `resolved` | check, muted |
| `offline`, `stopped`, `revoked`, `cancelled` | hollow ring, muted |
| `queued`, `pending` | dashed ring |
| `failed`, `unknown` | inverted (white on black) with "!" — needs a human |

**Why**: colour is not allowed, so shape + fill + weight carry the state. A new status needs a CSS rule; without one it falls back to an outlined ring.

### Convention: shared render helpers

Defined before `card()`, outside both test slices:

```js
reading(value, unit)            // .reading-value 32px + .reading-unit 13px muted
stat(title, value, foot, unit = '', positive = false)   // 4th arg is a unit, not an icon
meter(label, percent)           // 10 segments; known -> role="meter" + aria-valuenow, unknown -> aria-hidden bar + visible "—"
```

`trafficPage()` lives inside the `traffic-display.cjs` slice (`let trafficNodeId = ''` … `function protocolTable(`) and that harness only provides `esc/badge/bytes/date/icon/shell/names/nodes`. Never call `reading()`/`meter()` or any other outside helper from it.

#### Wrong
```js
// inside trafficPage(): ReferenceError in tests/traffic-display.cjs
`<td>${reading(total.value, 'GiB')}</td>`
```
#### Correct
```js
`<td class="num">${trafficValue(total.value)}</td>`
```

### Convention: user management lives after the test slices

**What**: the user management section (`usersPage`, `userDetail`, `userForm`, `linkDialog`, `membersDialog`, `userAction`, `userTraffic`) is appended at the end of `app.js` behind the marker comment `// ---------------------------------------------------------------- 用户管理（平台用户）`. `tests/platform-users.cjs` slices from that marker to the end of the file and stubs `esc/bytes/date/names/icon/meter/stat/shell/modal/api/post/$/nodes/location/submitTask`. Node authority (`authorityBlock`, `authorityDialog`) and one-click upgrade (`upgradeDialog`) live in the same section.

**Why**: `trafficPage()` may not call outside helpers, so the per-user traffic table is a separate `userTraffic()` that inserts `#user-traffic` before `.footer-note` after `trafficPage()` renders (also after `traffic-node`). Keep new user-management code after the marker; keep the `pu-` prefix for its `data-action` values (dispatched by `userAction`).

**Gotcha**: objects created inside the vm realm fail `assert.deepStrictEqual` against objects from the test realm; compare `JSON.parse(JSON.stringify(value))`.

Statuses that are not task states (`userStates`, `syncStates`) render through `stateBadge(map, key)` with an existing badge class, never a new colour.

### Pattern: whole-row link in the node list

`.node-row` is a grid row; the name `<a href="#nodes/ID">` gets `::after { position:absolute; inset:0 }` so the row is clickable. Keep every other interactive element out of `.node-row` (the overlay would cover it) and keep the inset focus outline on the link.

## Accessibility

- Choice lists are `<button type="submit" value="…">` inside a form; read the choice from `e.submitter?.value` and check it against the allowed list. This gives Tab/Enter/Space for free.
- Fields inside a collapsed `<details>` can block submission without a visible message. Listen for `invalid` in the capture phase on the form and open the `<details>` that contains the field.
- Do not `display: none` empty live regions (`role="status"`, `role="alert"`); collapse them with zero margin instead, or screen readers may miss later messages.

---

## Common Mistakes

### Common Mistake: changing submit payloads during a visual redesign

**Symptom**: a layout-only change alters the params sent by `submitTask(...)`.

**Cause**: fields are moved or regrouped and a conditional that built `params` is edited along with them.

**Fix / Prevention**: leave the submit handler and `update…()` rules alone in a visual change. Compare old and new `submitTask` arguments across every `core:protocol` × `install_options_version` combination before committing; `install-form.cjs` keeps the per-protocol param assertions.

## Filter menus

- List filters use `filterMenu(id, label, options, value)` from `app.js`, never a native `<select>`: a 32px button with the chevron right after the text, and a popover menu (`role="menu"`, options `role="menuitemradio"` with `aria-checked` and a check mark).
- The page binds `$('#id').onchange = e => ...`; the component calls it with `{target: {value}}` after a pick. Outside click, Escape, Tab, or opening another menu closes it; arrow keys move between options. The periodic refresh skips re-rendering while a menu is open.
- A non-default value gives the button a black border and bold text. Under `(pointer: coarse)` the button and options are at least 44px. Dialog form fields keep a native `<select>` in the markup: `modal()` calls `enhanceSelect()` on every select, which hides it (still the value source, `change` events and `required` validation) under a full-width 40px `.select-menu` built with `filterMenu(..., 'select-menu')`. Code keeps reading and writing `select.value`, `.disabled` and `.innerHTML`; a value setter override and a MutationObserver mirror those changes. The popover is `position: fixed` (placed by `selectMenuPlace`, flipping upward when needed) so the scrolling dialog body cannot clip it, and closes on scroll (after a 200ms grace period) or resize. Disabled `<option>`s become disabled menu items that keyboard navigation skips.

## Install flow target server

- Enter the install flow with `startInstall(nodeId)` (server detail: the current server; 节点管理「新建协议」: the 服务器 filter, else the first installable server). Both steps show a `#install-server` picker listing only adopted, online, non-maintenance, non-deleted servers; in the parameter step servers lacking the protocol are disabled.
- The install code reads the target through `installNode()` (`installTargetId`), never `selected`: the 10-second refresh re-renders a detail page and resets `selected`. `submitTask(..., node)` and `installPlaceUsers(users, nodeId)` take the target explicitly.

## Install dialog layout and dialog back

- `modal(title, body, wide, kind, back)`: pass `back` to show a left arrow next to the close button; there is no in-form back button.
- The install parameter step is one page: `.install-top` holds inline `服务器` / `内核` fields (label left, auto-width select menu), then a one-line `#protocol-guidance`, then a two-column `.install-grid` (one column under 760px). Group wrappers (`#certificate-fields`, `#reality-fields`, `#snell-fields`) are `.install-group` with `display: contents` so their fields flow into the grid; keep every field id stable because `updateFields()` toggles them. No section headings, no `<details>`; generated credentials use the placeholder 「留空自动生成」.

## Control height

- Buttons (including `button.small` and tabs), inputs, and dialog select menus are all 40px tall. Exceptions: buttons inside tables (`td button`, 32px), list filter menus and the filter search box (32px, kept compact on request), and the dialog close/back icon buttons (36px). Under `(pointer: coarse)` everything is at least 44px.

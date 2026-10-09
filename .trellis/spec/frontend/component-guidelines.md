# Component Guidelines

> How UI pieces are built in the Vaio Panel front end (`platform/web/`).

---

## Overview

The panel is a single vanilla-JS file (`platform/web/app.js`) plus one stylesheet (`platform/web/style.css`). There is no framework and no build step. Views and dialogs are functions that build an HTML template string and assign it, then attach handlers by element id with `$('#id')`. UI text is Chinese; the visual style is black and white minimal (see `CLAUDE.md`).

---

## Component Structure

- A view or dialog is one function: render markup, then wire handlers, then call a local `update…()` that applies hidden/disabled/required state.
- Dialogs go through `modal(title, body, wide = false, extraClass = '')` (`app.js:140`). It replaces the dialog's innerHTML, so listeners attached to the previous body are dropped with it; re-attach on every render.
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

- Only the variables on `:root` in `style.css` (`--ink`, `--muted`, `--line`, `--surface`, `--accent-soft`); no new colours.
- Groups are a 13px/600 heading over a 1px `--line` top divider. Use `fieldset` for semantics with `border: 0; padding: 0`, not boxed sets.
- An inline action next to an input ("生成") uses `.input-action` (`grid-template-columns: 1fr auto`) and keeps the button's id.
- A long dialog keeps the head and `.modal-foot` fixed and scrolls only the middle (`.install-scroll`), so the primary button is always visible.
- Narrow screens use the existing 760px breakpoint; check 375px for horizontal scroll.

---

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

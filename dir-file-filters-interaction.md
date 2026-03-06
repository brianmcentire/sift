# Directory + File Filter Interaction Notes

## Why this came up

During manual QA of the new Tree/List view behavior, a UX mismatch was observed:

1. In **Tree View**, entering a directory query behaves as expected (directory expansion/navigation).
2. Then entering a filename query opens the **file-results overlay** (also expected).
3. In that overlay state, the directory search box remains populated, but it no longer constrains the shown file results.

From a user perspective, this can feel inconsistent because a visible filter appears active but has no effect on the current result set.

---

## Problem statement

The interaction between directory search and filename/hash search needs clearer, explicit semantics in both modes:

- **Tree View** (navigation-centric + overlay flows)
- **List View** (flat result set with server-side paging/filtering)

Without explicit rules, users may misinterpret whether multiple visible filters are combined, paused, or mutually exclusive.

---

## Options discussed

## 1) Auto-clear directory query when entering file/hash overlay

**Behavior:** When filename/hash overlay activates in Tree View, clear `dirQuery` automatically.

**Pros**
- Eliminates ambiguity quickly.
- Very small implementation surface.
- No backend changes.

**Cons**
- User loses typed directory context.
- Can feel abrupt if they expected to go back.

**Implementation cost:** Low  
**Performance impact:** None

## 2) Keep directory text, but disable directory input while overlay is active

**Behavior:** Preserve typed directory query, but disable directory control in overlay mode with explicit helper state/message.

**Pros**
- Makes "not currently applied" explicit.
- Preserves user input for return to tree context.
- Low-risk behavior change.

**Cons**
- Slightly more UI state complexity.
- Still relies on users noticing disabled state/message.

**Implementation cost:** Low  
**Performance impact:** None

## 3) Apply directory query as an additional filter to overlay results

**Behavior:** In Tree overlay modes, directory query also filters the overlay file rows.

**Pros**
- Most intuitive "all visible filters combine" model.
- No dead-looking input.

**Cons**
- Requires careful semantics definition (contains vs prefix, per overlay type).
- Risk of hiding expected duplicate click-through rows in pinned/dup overlays.
- Potentially broader regression surface.

**Implementation cost:** Medium  
**Performance impact:** Low-Medium (typically client-side filter on overlay rows)

## 4) Keep behavior, add explicit banner/chip that directory filter is paused

**Behavior:** Overlay shows a clear note that directory filter is not applied in this mode.

**Pros**
- Minimal logic changes.
- Transparent to users.

**Cons**
- Adds UI copy/noise.
- Does not resolve underlying interaction complexity.

**Implementation cost:** Low-Medium  
**Performance impact:** None

## 5) Unify search into one query model across Tree overlay and List View

**Behavior:** Define a single composable filter model and apply consistently everywhere.

**Pros**
- Strong long-term consistency.
- Easier to explain once complete.

**Cons**
- Largest change/risk.
- Requires refactor of currently working overlay flows and likely backend/API contracts.

**Implementation cost:** High  
**Performance impact:** Variable (depends on architecture)

---

## Suggested near-term direction

Prefer a low-risk clarification step first:

- **Option 2** (disable + preserve value) or
- **Option 1** (auto-clear, simplest)

Then revisit whether Option 3 or 5 is worth the additional complexity once semantics are finalized.

---

## Follow-up design question to settle later

When filename/hash overlay is active in Tree View, should directory input be:

1. cleared,
2. paused/disabled,
3. composable as an active filter?

The answer should be explicit and documented in the same place as Tree/List search semantics.

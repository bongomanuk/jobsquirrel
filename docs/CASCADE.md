# How Cascade is integrated

The dashboard uses **[Cascade](https://github.com/erobwen/liquefy)**, the reactive
UI framework by **Robert Renbris**, for its dynamic surfaces. This page is the
map of that integration: what is on Cascade, how the vanilla application talks to
it, and what deliberately stays outside it.

Cascade is licensed under the ISC License; the vendored copy's notice and
package versions are in `tools/web/vendor/cascade.NOTICE`. See also
[Credits](CREDITS.md).

## The bundle and the islands

The dashboard is still served as static files with no build step. Cascade is
vendored once as a browser ESM bundle:

- `tools/web/vendor/cascade.js` is built with esbuild from
  `@liquefy/cascade.reactive`, `.component`, `.dom` and the overlay part of
  `.ui`. The exact entry and versions are in `vendor/cascade.NOTICE`.
- `tools/web/cascade-islands.js` imports that bundle and mounts the islands.
- `tools/dashboard.py` serves and fingerprints both files, and reloads an open
  tab when they change.

An **island** is a small Cascade component tree rendered onto one existing DOM
element. The rest of the page remains the application's own JavaScript. Each
island has a tiny API on `window.CascadeIslands`, and the vanilla side calls it
with a plain view model. If the module is unavailable, the old markup is used or
the original controls are revealed.

The grid's aggregate model is a Cascade **store** rather than a component tree.
`tools/web/grid-stats.js` derives the bucket, status, sub-state, shelved and
scam counts in one pass; `cascade-islands.js` wraps that derivation in one
`observable` and exposes it as `CascadeIslands.stats`. `app.js` publishes the
raw rows after each `/api/grid` load and reads the snapshot for the bucket
chips, the state map, the tooltips and the sub-state filter. There is no second
count derivation for those surfaces to drift from.

## What each island covers

| Surface | Components | Cascade features | The vanilla side |
| --- | --- | --- | --- |
| Activity run roster | `ActivityRoster` | component state, `flipAnimationContainer` | computes the roster from the live run and calls `CascadeIslands.activity.set(view)` |
| Grid rows | `GridRows`, `RawRow` | custom `DOMNodeComponent`, keyed rows, `flipAnimationContainer` with `display: contents` so rows stay real `<tr>` elements | filters, sorts, groups and selection still compute the row models |
| Grid aggregate model | `CascadeIslands.stats` (`observable`) | one reactive store over the pure `grid-stats.js` derivation | publishes `GRID` and the bucket classifier; reads counts for the chips, state map, tooltips and sub-state filter |
| Role drawer | `DrawerTabs`, `DrawerBody`, `RawBlock` | state-driven tabs, raw block for the existing tab HTML | the seven tab renderers and their actions |
| Grid toolbar | `ToolbarExtra` | `overflowContainer`, `elementSlot`, `elementBoundsProvider` | the original buttons stay hidden as the click handlers |
| Knowledge search results | `KgResults` | keyed result components, `flipAnimationContainer` | search and graph navigation |
| Knowledge side tabs | `KgTabs` | state-driven tabs | the tab content |
| Context menu | `CtxMenuRoot` | `overlayFrame`, `overlay`, nested submenus | `App.rowMenu` still builds the item model and actions |
| Role URLs and page title | module-level router and head | `browserLocation`, `documentHead` | row opening/closing and the page title text |

## Data flow

The application owns the data. A typical update looks like this:

1. The vanilla code fetches or computes something (a run roster, grid row
   models, the current drawer tab).
2. It calls the island's small API, for example
   `CascadeIslands.grid.set(models)` or `CascadeIslands.activity.set(view)`.
3. Cascade diffs the component tree and patches only the nodes that changed.
   `flipAnimationContainer` animates elements that move, appear or leave.

The islands never fetch. They receive plain data and callbacks, so the
application's permissions, state and rendering rules stay in one place.

The aggregate model follows the same rule. `grid-stats.js` is a pure function
over rows and a bucket classifier; the Cascade store only holds its latest
snapshot. A filter keystroke does not recompute it. A new `/api/grid` response
does, once, and every surface reads the same numbers.

## What stays outside Cascade

- **The 3D graph canvases.** The map and universe views are Three.js renderers
  with their own layout and input. Cascade owns the surrounding search results
  and tabs, not the canvas.
- **The row list pipeline.** `GRID`, filtering, sorting, grouping, selection and
  the register remain the existing JavaScript engine. The aggregate model moved
  to Cascade, but the filtered row list is cheap at roughly a thousand rows and
  is tightly coupled to actions (prepare shown, submit prepared, export, bulk
  selection). Rewriting that path in observables would add indirection without a
  measured gain. If the grid grows into the tens of thousands of rows, this is
  the next surface to revisit.
- **Dialog contents.** The raw-log, legend, settings, ask and enrichment dialogs
  are still plain HTML. The context menu is the first overlay; the rest can
  follow the same `overlayFrame` pattern.
- **Themed widgets.** `cascade.ui` is bundled only for the overlay frame. The
  dashboard keeps its own pastel design rather than adopting Cascade's widgets.

## Rebuilding the bundle

The bundle is generated, not hand-edited. From a checkout with node and npm:

```bash
npm install @liquefy/cascade.component @liquefy/cascade.dom @liquefy/cascade.reactive @liquefy/cascade.ui esbuild
npx esbuild entry.js --bundle --format=esm --minify --outfile=tools/web/vendor/cascade.js
```

`entry.js` is the export list recorded in `tools/web/vendor/cascade.NOTICE`.

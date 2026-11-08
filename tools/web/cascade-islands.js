/* Cascade islands.
 *
 * The dashboard is still mostly plain JavaScript; this module starts moving the
 * dynamic surfaces onto Cascade (https://github.com/erobwen/liquefy), one
 * isolated island at a time. The first island is the Activity run roster: the
 * live counts, running roles and per-role outcomes inside a
 * flipAnimationContainer, so a role appearing, moving or changing outcome
 * animates without the pane being re-rendered by string concatenation.
 *
 * The vanilla side calls window.CascadeIslands.activity.set(view) with the same
 * view object runRoster() produces. Everything else in the pane stays vanilla
 * for now.
 */
import {
  Component, RenderContext, DOMElementTarget, DOMNodeComponent, observable, documentHead,
  browserLocation, overflowContainer, elementSlot, elementBoundsProvider,
  overlayFrame, overlay,
  div, span, a, b, ul, li, details, summary, text, button, flipAnimationContainer,
} from './vendor/cascade.js';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/* The page title and the URL are Cascade state too: documentHead follows an
 * observable title, and browserLocation turns the open role into a real address
 * (/role/<key>) with back/forward. The vanilla app calls the two small handles
 * below; the framework does the rest. */
const pageHead = observable({ title: 'Jobsquirrel' });
try {
  documentHead(() => ({ title: pageHead.title }));
} catch (e) { /* a browser without the head helper keeps the static title */ }
let location = null;
try {
  location = browserLocation({ base: '/' });
} catch (e) { location = null; }

class ActivityRoster extends Component {
  initialState() {
    return { view: null };
  }

  build() {
    const v = this.view;
    if (!v || !v.total) return div({ key: 'empty' });

    // Outcome counts, in the order the statuses first appear.
    const counts = new Map();
    for (const x of v.done || []) {
      const s = String(x.status || 'no result').toUpperCase();
      counts.set(s, (counts.get(s) || 0) + 1);
    }
    const bits = [];
    if ((v.running || []).length) bits.push(`${v.running.length} running`);
    for (const [s, n] of counts) bits.push(`${n} ${s.toLowerCase()}`);
    if ((v.waiting || []).length) bits.push(`${v.waiting.length} waiting`);

    const head = div(
      { key: 'head', className: 'mini' },
      text('This run: '),
      b(text(String(v.total))),
      text(` ${v.total === 1 ? 'role' : 'roles'} · ${bits.length ? bits.join(' · ') : 'nothing yet'}`),
    );

    const children = [head];

    if ((v.running || []).length) {
      children.push(div(
        { key: 'running', className: 'mini muted' },
        text('Running now: ' + v.running.map((x) => x.label).join(' · ')),
      ));
    }

    if ((v.done || []).length) {
      const open = v.done.length <= 12;
      children.push(details(
        { key: 'outcomes', className: 'act-raw', open },
        summary(text(`Outcomes · ${plural(v.done.length, 'role')}`)),
        ul(
          { className: 'act-list' },
          ...v.done.map((x) => li(
            { key: `${x.label}|${x.status || ''}|${String(x.reason || '').slice(0, 40)}` },
            b(text(`${x.label} · ${x.status || 'NO RESULT'}`)),
            text(x.reason ? `: ${String(x.reason).slice(0, 240)}` : ''),
          )),
        ),
      ));
    }

    if ((v.waiting || []).length) {
      children.push(details(
        { key: 'waiting', className: 'act-raw' },
        summary(text(`Waiting in this run · ${plural(v.waiting.length, 'role')}`)),
        ul(
          { className: 'act-list' },
          ...v.waiting.map((x) => li({ key: `w|${x.label}` }, text(x.label))),
        ),
      ));
    }

    return flipAnimationContainer(
      { key: 'roster', speed: 1.15, style: { display: 'block' } },
      ...children,
    );
  }
}

/* The grid's rows. The cell markup is the existing, battle-tested HTML for one
 * row; Cascade owns the row element, its identity and its place, and the flip
 * container animates it. The container's div is display:contents so the rows
 * are still real table rows inside the tbody. */
class RawRow extends DOMNodeComponent {
  setProperties({ html, cls, keyName, rowId, index, group }) {
    this.html = html;
    this.cls = cls;
    this.keyName = keyName;
    this.rowId = rowId;
    this.index = index;
    this.group = group;
  }

  ensureNode() {
    let el = this.unobservable.node;
    if (!el) {
      el = document.createElement('tr');
      this.unobservable.node = el;
    }
    if (el._html !== this.html) {
      el.innerHTML = this.html || '';
      el._html = this.html;
    }
    const cls = this.cls || '';
    if (el.className !== cls) el.className = cls;
    if (this.keyName != null) el.dataset.key = this.keyName;
    else el.removeAttribute('data-key');
    if (this.rowId != null) el.dataset.id = this.rowId;
    else el.removeAttribute('data-id');
    if (Number.isInteger(this.index) && this.index >= 0) {
      el.onclick = (ev) => App.rowClick(ev, this.index);
      el.oncontextmenu = (ev) => { ev.preventDefault(); App.rowMenu(ev, this.index); };
    } else if (this.group) {
      const g = this.group;
      el.onclick = () => window.toggleGroup(g);
      el.oncontextmenu = null;
    } else {
      el.onclick = null;
      el.oncontextmenu = null;
    }
    return el;
  }
}

class GridRows extends Component {
  initialState() {
    return { models: [] };
  }

  build() {
    return flipAnimationContainer(
      { key: 'rows', style: { display: 'contents' } },
      ...this.models.map((m) => new RawRow({ key: m.key, ...m })),
    );
  }
}

/* The role drawer: its tab bar and its content. The tab content is still the
 * existing, heavily data-driven HTML; Cascade owns the tabs, the active state
 * and the body element, so opening a tab and switching tabs is component work
 * rather than innerHTML surgery. The content itself is an island (a raw block)
 * until its sections are ported one by one. */
class RawBlock extends DOMNodeComponent {
  setProperties({ html, className }) {
    this.html = html;
    this.className = className || '';
  }

  ensureNode() {
    let el = this.unobservable.node;
    if (!el) {
      el = document.createElement('div');
      this.unobservable.node = el;
    }
    if (el._html !== this.html) {
      el.innerHTML = this.html || '';
      el._html = this.html;
    }
    if (el.className !== this.className) el.className = this.className;
    return el;
  }
}

class DrawerTabs extends Component {
  initialState() {
    return { tabs: [], active: 0 };
  }

  build() {
    return div(
      { key: 'tabs', style: { display: 'contents' } },
      ...this.tabs.map((t, i) => a(
        { key: `${i}:${t}`, className: i === this.active ? 'on' : '', onclick: () => window.dt(i) },
        text(t),
      )),
    );
  }
}

class DrawerBody extends Component {
  initialState() {
    return { html: '' };
  }

  build() {
    return new RawBlock({ key: 'body', html: this.html, className: 'drawer-body-inner' });
  }
}

let activity = null;
const host = document.getElementById('act-roster');
if (host) {
  host.innerHTML = '';                       // drop a vanilla fallback, if any
  const inst = new ActivityRoster({});
  inst.establish().renderOnto(
    DOMElementTarget.forElement(host),
    new RenderContext({}),
  );
  activity = {
    ready: () => true,
    set: (view) => { inst.view = view || null; },
  };
}

/* The toolbar's secondary actions. Cascade measures the row and moves whatever
 * does not fit into the More menu, so the grid keeps its primary actions when
 * it is docked to a narrow edge. The hidden originals keep the existing click
 * handlers; these buttons just click them. */
class ToolbarExtra extends Component {
  initialState() {
    return { more: false, overflow: 0 };
  }

  build() {
    const slot = elementSlot({
      key: 'slot',
      style: { display: 'flex', flexDirection: 'column', gap: '2px' },
    });
    const click = (id) => () => { const el = document.getElementById(id); if (el) el.click(); };
    const items = [
      button({ key: 'export', className: 'small', onclick: click('export') }, text('Export CSV')),
      button({ key: 'match', className: 'small', onclick: click('a-match') }, text('Match')),
      button({ key: 'legend', className: 'small', onclick: click('legend') }, text('Legend')),
    ];
    const more = button(
      { key: 'more', className: 'small', onclick: () => { this.more = !this.more; } },
      text(this.overflow ? `More (${this.overflow})` : 'More'),
    );
    const row = overflowContainer({
      key: 'row',
      children: items,
      ellipsis: this.overflow ? more : null,
      overflowSlot: slot,
      onOverflow: (n) => { if (n !== this.overflow) this.setState({ overflow: n }); },
      style: { display: 'flex', gap: '4px', minWidth: 0, width: '100%', flex: '1 1 auto', alignItems: 'center' },
    });
    return div(
      { key: 'wrap', className: 'toolbar-extra', style: { position: 'relative', display: 'flex', minWidth: 0, width: '100%', flex: '1 1 auto' } },
      elementBoundsProvider({ key: 'bounds', child: row, style: { display: 'flex', minWidth: 0, flex: '1 1 auto' } }),
      div(
        { key: 'pop', className: 'toolbar-more', style: { display: this.more && this.overflow ? 'flex' : 'none' } },
        slot,
      ),
    );
  }
}

/* The knowledge page's search results and side tabs. The results are a real
 * list of components now, so a new search replaces them with a short cascade
 * instead of an innerHTML swap; the tabs have the same state-driven active
 * class as the role drawer. The graph canvases stay with Three.js. */
class KgResults extends Component {
  initialState() {
    return { view: null };
  }

  build() {
    const v = this.view;
    if (!v) return div({ key: 'empty' });
    const head = div(
      { key: 'head', className: 'kg-res-head' },
      text(v.head || ''),
      button({ key: 'close', className: 'small', onclick: () => App.graphHideResults() }, text('✕')),
    );
    const groups = (v.groups || []).map((g) => div(
      { key: `g:${g.label}`, className: 'kg-res-group' },
      b(text(g.label)),
      ...g.items.map((it) => button(
        {
          key: `${g.label}:${it.title}`,
          className: 'kg-res-item',
          onclick: () => (it.kind === 'community' ? App.graphCommunity(it.id) : App.graphEgo(it.id)),
        },
        b(text(it.title)),
        span({ className: 'muted mini' }, text(it.sub || '')),
      )),
    ));
    return flipAnimationContainer({ key: 'wrap', speed: 1.15, style: { display: 'block' } }, head, ...groups);
  }
}

class KgTabs extends Component {
  initialState() {
    return { active: 'details' };
  }

  build() {
    const tabs = ['details', 'classes', 'roles', 'sources', 'add'];
    return div(
      { key: 'tabs', style: { display: 'contents' } },
      ...tabs.map((t) => button(
        {
          key: t,
          className: this.active === t ? 'on' : '',
          onclick: () => App.kgSide(t),
        },
        text(t === 'details' ? 'Details' : t === 'classes' ? 'Classes' : t === 'roles' ? 'Roles' : t === 'sources' ? 'Sources' : 'Add'),
      )),
    );
  }
}

/* The context menu as a Cascade overlay. The vanilla menu builder still decides
 * what to show (the same items and actions as before); this renders it above the
 * page, with submenus and keyboard dismissal. */
class RawInline extends DOMNodeComponent {
  setProperties({ html, className }) {
    this.html = html;
    this.className = className || '';
  }

  ensureNode() {
    let el = this.unobservable.node;
    if (!el) {
      el = document.createElement('span');
      this.unobservable.node = el;
    }
    if (el._html !== this.html) { el.innerHTML = this.html || ''; el._html = this.html; }
    if (el.className !== this.className) el.className = this.className;
    return el;
  }
}

class CtxMenuRoot extends Component {
  initialState() {
    return { menu: null, x: 0, y: 0, sub: null };
  }

  show(items, head, x, y) {
    const w = Math.min(360, Math.max(220, innerWidth - 16));
    const h = Math.min(520, Math.max(160, innerHeight - 16));
    this.menu = { items: items || [], head: head || '' };
    this.x = Math.max(6, Math.min(x || 40, innerWidth - w - 8));
    this.y = Math.max(6, Math.min(y || 40, innerHeight - h - 8));
    this.sub = null;
  }

  hide() {
    this.menu = null;
    this.sub = null;
  }

  itemButton(it, i, isSub = false) {
    return button(
      {
        key: (isSub ? 's' : 'm') + i,
        className: 'ctx-item' + (it.danger ? ' danger' : '') + (it.disabled ? ' disabled' : '') + (it.sub ? ' has-sub' : ''),
        disabled: !!it.disabled,
        onclick: (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          if (it.disabled) return;
          if (it.sub) { this.openSub(i, ev.currentTarget); return; }
          this.hide();
          it.run(ev.currentTarget);
        },
        onmouseenter: (ev) => {
          if (it.sub) this.openSub(i, ev.currentTarget);
          else if (!isSub) this.sub = null;
        },
      },
      new RawInline({ className: 'ctx-ico', html: it.icon || '' }),
      span({ className: 'ctx-lbl' }, text(it.label || '')),
      it.hint ? span({ className: 'ctx-hint' }, text(it.hint)) : null,
      it.sub ? span({ className: 'ctx-arrow' }, text('›')) : null,
    );
  }

  openSub(i, el) {
    const menu = this.menu;
    const it = menu && menu.items[i];
    if (!it || !it.sub) return;
    const r = el.getBoundingClientRect();
    const subW = 230;
    const subH = Math.min(420, it.sub.length * 32 + 16);
    let left = r.right + 4;
    if (left + subW > innerWidth - 8) left = r.left - subW - 4;
    this.sub = {
      items: it.sub,
      x: Math.max(6, left),
      y: Math.max(6, Math.min(r.top - 6, innerHeight - subH - 8)),
    };
  }

  build() {
    const m = this.menu;
    const s = this.sub;
    let content = div({ key: 'none' });
    if (m) {
      const panel = div(
        { key: 'menu', className: 'ctxmenu cascade-ctx',
          style: { position: 'fixed', left: this.x + 'px', top: this.y + 'px', pointerEvents: 'auto', zIndex: 95 } },
        m.head ? new RawBlock({ key: 'head', className: 'ctx-head', html: m.head }) : null,
        ...m.items.map((it, i) => it.sep ? div({ key: 'sep' + i, className: 'ctx-sep' }) : this.itemButton(it, i)),
      );
      const subpanel = s ? div(
        { key: 'sub', className: 'ctxmenu ctx-sub cascade-ctx',
          style: { position: 'fixed', left: s.x + 'px', top: s.y + 'px', pointerEvents: 'auto', zIndex: 96 } },
        ...s.items.map((it, i) => it.sep ? div({ key: 'ssep' + i, className: 'ctx-sep' }) : this.itemButton(it, i, true)),
      ) : null;
      content = div({ key: 'wrap', style: { display: 'contents' } }, panel, subpanel);
    }
    return overlayFrame(
      { key: 'frame', style: { position: 'fixed', inset: 0, zIndex: 90, pointerEvents: 'none' },
        children: [overlay({ key: 'ov', showing: !!m, children: [content] })] },
    );
  }
}

let drawer = null;
const tabsHost = document.getElementById('dtabs');
const bodyHost = document.getElementById('d-body');
if (tabsHost && bodyHost) {
  tabsHost.innerHTML = '';                    // drop any vanilla fallback tabs
  bodyHost.innerHTML = '';
  const tabs = new DrawerTabs({});
  tabs.establish().renderOnto(DOMElementTarget.forElement(tabsHost), new RenderContext({}));
  const body = new DrawerBody({});
  body.establish().renderOnto(DOMElementTarget.forElement(bodyHost), new RenderContext({}));
  drawer = {
    ready: () => true,
    open: (list, active, html) => {
      tabs.tabs = Array.isArray(list) ? list : [];
      tabs.active = active || 0;
      body.html = html || '';
    },
    tab: (active, html) => {
      tabs.active = active || 0;
      body.html = html || '';
    },
  };
}

const toolbarHost = document.getElementById('toolbar-extra');
if (toolbarHost) {
  try {
    const tb = new ToolbarExtra({});
    tb.establish().renderOnto(DOMElementTarget.forElement(toolbarHost), new RenderContext({}));
  } catch (e) {
    // If the island cannot render, keep the original buttons reachable instead
    // of leaving the toolbar without them.
    const fallback = toolbarHost.nextElementSibling;
    if (fallback) fallback.classList.remove('hide');
  }
}

let menu = null;
const menuHost = document.getElementById('cascade-overlays');
if (menuHost) {
  const mi = new CtxMenuRoot({});
  mi.establish().renderOnto(DOMElementTarget.forElement(menuHost), new RenderContext({}));
  menu = {
    ready: () => true,
    show: (items, head, x, y) => mi.show(items, head, x, y),
    hide: () => mi.hide(),
  };
}

let knowledge = null;
const krHost = document.getElementById('kg-results');
const ktHost = document.querySelector('.kg-side-tabs');
let krInst = null, ktInst = null;
if (krHost && ktHost) {
  krHost.innerHTML = '';
  ktHost.innerHTML = '';
  krInst = new KgResults({});
  krInst.establish().renderOnto(DOMElementTarget.forElement(krHost), new RenderContext({}));
  ktInst = new KgTabs({});
  ktInst.establish().renderOnto(DOMElementTarget.forElement(ktHost), new RenderContext({}));
  knowledge = {
    ready: () => true,
    results: (view) => { krInst.view = view || null; },
    tab: (tab) => { ktInst.active = tab || 'details'; },
  };
}

let grid = null;
const gridHost = document.getElementById('rows');
if (gridHost) {
  gridHost.innerHTML = '';                    // drop the vanilla fallback rows
  const inst = new GridRows({});
  inst.establish().renderOnto(
    DOMElementTarget.forElement(gridHost),
    new RenderContext({}),
  );
  grid = {
    ready: () => true,
    set: (models) => { inst.models = models || []; },
  };
}

window.CascadeIslands = window.CascadeIslands || {};
window.CascadeIslands.activity = activity || {
  ready: () => false,
  set: () => {},
};
window.CascadeIslands.grid = grid || {
  ready: () => false,
  set: () => {},
};
window.CascadeIslands.drawer = drawer || {
  ready: () => false,
  open: () => {},
  tab: () => {},
};
window.CascadeIslands.menu = menu || {
  ready: () => false,
  show: () => {},
  hide: () => {},
};
window.CascadeIslands.knowledge = knowledge || {
  ready: () => false,
  results: () => {},
  tab: () => {},
};
window.CascadeIslands.head = {
  set: (title) => { pageHead.title = title || 'Jobsquirrel'; },
};
window.CascadeIslands.router = location ? {
  path: () => {
    const p = location.path;
    return Array.isArray(p) ? p.slice() : [];
  },
  navigate: (parts, options) => location.navigate(parts, options),
  href: (parts) => location.href(parts),
} : null;
window.dispatchEvent(new Event('cascade-ready'));

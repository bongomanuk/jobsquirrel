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
  browserLocation, div, a, b, ul, li, details, summary, text, flipAnimationContainer,
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

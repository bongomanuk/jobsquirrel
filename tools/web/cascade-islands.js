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
  Component, RenderContext, DOMElementTarget, div, b, ul, li, details, summary,
  text, flipAnimationContainer,
} from './vendor/cascade.js';

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

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

window.CascadeIslands = window.CascadeIslands || {};
window.CascadeIslands.activity = activity || {
  ready: () => false,
  set: () => {},
};
window.dispatchEvent(new Event('cascade-ready'));

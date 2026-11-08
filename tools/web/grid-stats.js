/* The grid's aggregate model.
 *
 * One pass over the raw rows produces every number the dashboard shows about
 * the application set: the bucket chips, the state map, the per-status
 * tooltips and the sub-state filter all read this snapshot. Keeping it in one
 * place is the point: when these numbers were derived separately, a shelved
 * role could be counted under its old status while the matching view showed
 * nothing.
 *
 * The row list itself (filter, sort, group, cell markup) stays in app.js. This
 * module is data only: no DOM, no fetch, no Cascade dependency. cascade-
 * islands.js wraps it in a Cascade observable store; app.js reads the store.
 */
(function (root) {
  function derive(rows, bucketOf) {
    const classify = typeof bucketOf === 'function' ? bucketOf : () => 'pipeline';
    const buckets = { scams: 0, shelved: 0, needs: 0, prepared: 0, ongoing: 0, pipeline: 0, done: 0 };
    const status = {};
    const shelvedBy = {};
    const substates = {};
    let shelved = 0, scams = 0, focus = 0;

    for (const r of rows || []) {
      const b = r.shelved ? 'shelved' : classify(r);
      buckets[b] = (buckets[b] || 0) + 1;
      if (r.shelved) {
        shelved++;
        shelvedBy[r.status] = (shelvedBy[r.status] || 0) + 1;
        continue;                       // a parked role is out of the active model
      }
      status[r.status] = (status[r.status] || 0) + 1;
      if (r.scam && ['high', 'medium'].includes(r.scam.level)) scams++;
      if (r.focus || r.focus_unknown) focus++;
      if (r.substate) {
        const k = r.status + ':' + r.substate;
        if (!substates[k]) {
          substates[k] = {
            status: r.status,
            key: r.substate,
            label: r.substate_label || r.substate,
            hint: r.substate_hint || '',
            n: 0,
          };
        }
        substates[k].n++;
      }
    }

    return {
      buckets,
      status,
      shelvedBy,
      substates,
      shelved,
      scams,
      focus,
      active: buckets.scams + buckets.needs + buckets.prepared + buckets.ongoing + buckets.pipeline,
      all: (rows || []).length,
    };
  }

  const api = { derive };
  root.GridStats = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);

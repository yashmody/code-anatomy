// framework.json is the navigation source of truth (order, nesting, telescoping).
// Scroll orders sections by it; Read paginates within a chapter and telescopes via opensInto.
import { loadJSON } from './load.js';

export async function loadFramework(base) {
  return loadJSON(`${base}/course/framework.json`);
}

// Flatten the rings into one ordered address list + a lookup by id.
export function indexFramework(fw) {
  const order = [];
  const byId = {};
  for (const ring of fw.rings) {
    byId[ring.id] = { ...ring, kind: 'ring' };
    order.push(ring.id);
    for (const l of ring.letters || []) {
      byId[l.id] = { ...l, kind: 'letter', ringId: ring.id };
      order.push(l.id);
    }
    for (const m of ring.modules || []) {
      byId[m.id] = { ...m, kind: 'module', ringId: ring.id };
      order.push(m.id);
    }
  }
  return { order, byId, rings: fw.rings };
}

export function orderIndex(idx, address) {
  const i = idx.order.indexOf(address);
  return i < 0 ? Number.MAX_SAFE_INTEGER : i;
}

// The ring/letter a chapter telescopes into, if any (e.g. code.e → coder, coder.c → anatomy).
export function opensInto(idx, address) {
  const node = idx.byId[address];
  return node && node.opensInto ? node.opensInto : null;
}

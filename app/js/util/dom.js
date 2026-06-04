// Tiny DOM/string helpers shared by every renderer.
// esc() — escape text for safe interpolation (use for DATA fields: labels, notes, author text).
// raw() — pass authored HTML through verbatim (use for the `html` field: re-shell, never reword).
export const esc = (s) =>
  String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

export const raw = (s) => (s == null ? '' : String(s));

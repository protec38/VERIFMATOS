
// Helper for JSON fetch with CSRF
async function api(url, options={}){
  const opts = Object.assign({ headers: {} }, options);
  if (!opts.headers['Content-Type'] && opts.body && !(opts.body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
  }
  opts.headers['X-CSRFToken'] = window.CSRF_TOKEN || '';
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
window.api = api;

// Fetch JSON from the content-architecture package (the data+contract sibling of app/).
export async function loadJSON(url) {
  let targetUrl = url;
  if (url.includes('/course/framework.json')) {
    targetUrl = '/api/course/framework';
  } else if (url.includes('/course/sections/')) {
    const filename = url.substring(url.lastIndexOf('/') + 1);
    targetUrl = `/api/course/chapters/${filename}`;
  }

  const res = await fetch(targetUrl, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${targetUrl}`);
  return res.json();
}

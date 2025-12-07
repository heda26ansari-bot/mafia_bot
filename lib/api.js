export async function apiFetch(path, opts = {}) {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const res = await fetch(base + path, {
    credentials: "include", // if using cookies
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {})
    },
    ...opts
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

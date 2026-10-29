export function readCommandHistory(key: string): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === "string" && /^[a-z][a-z0-9-]{0,40}$/.test(id)))].slice(0, 5) : [];
  } catch { return []; }
}

export function rememberCommand(key: string, id: string, previous: string[]): string[] {
  const next = [id, ...previous.filter((value) => value !== id)].slice(0, 5);
  try { localStorage.setItem(key, JSON.stringify(next)); } catch {}
  return next;
}

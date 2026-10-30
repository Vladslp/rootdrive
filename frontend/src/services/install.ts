export type InstallPrompt = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };
let prompt: InstallPrompt | null = null;
const subscribers = new Set<() => void>();
window.addEventListener("beforeinstallprompt", (event) => { event.preventDefault(); prompt = event as InstallPrompt; subscribers.forEach((callback) => callback()); });
window.addEventListener("appinstalled", () => { prompt = null; subscribers.forEach((callback) => callback()); });
export const installation = {
  get: () => prompt,
  subscribe: (callback: () => void) => { subscribers.add(callback); return () => { subscribers.delete(callback); }; },
  clear: () => { prompt = null; subscribers.forEach((callback) => callback()); },
};

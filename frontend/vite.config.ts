import { cpSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
const assets = fileURLToPath(
  new URL("./public/assets/pdfjs/", import.meta.url),
);
mkdirSync(assets, { recursive: true });
for (const folder of ["cmaps", "standard_fonts", "wasm"])
  cpSync(
    fileURLToPath(
      new URL("./node_modules/pdfjs-dist/" + folder, import.meta.url),
    ),
    assets + folder,
    { recursive: true },
  );
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});

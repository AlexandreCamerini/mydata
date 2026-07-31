import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// O build sai em web/dist e é servido pelo próprio FastAPI — um serviço só
// no Railway, não dois. Duas entradas, duas superfícies: index.html é a
// administração (montada em /admin) e apresentacao.html é a apresentação
// (servida na raiz). A base /admin/ vale para as duas de propósito: os
// assets saem sempre por /admin/assets, que o mount existente já serve.
export default defineConfig({
  base: "/admin/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        admin: "index.html",
        apresentacao: "apresentacao.html",
      },
    },
  },
  server: {
    proxy: {
      "/admin/api": "http://127.0.0.1:8000",
      "/v1": "http://127.0.0.1:8000",
    },
  },
});

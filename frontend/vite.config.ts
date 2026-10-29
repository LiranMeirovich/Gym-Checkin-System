// One Vite project, two separate builds (decision 0020):
//
//   --mode admin   src/admin  -> dist/admin   served by the admin app (8000)
//   --mode public  src/public -> dist/public  served by the public app (8001)
//
// The public build must never contain admin code: the public app is the
// one reachable from the internet. The guard below fails the public build
// if anything in it pulls in a file from src/admin.
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const APPS = {
  admin: { devPort: 5173, backend: "http://127.0.0.1:8000" },
  public: { devPort: 5174, backend: "http://127.0.0.1:8001" },
} as const;

type AppName = keyof typeof APPS;

const srcDir = (name: string) =>
  fileURLToPath(new URL(`./src/${name}/`, import.meta.url));

export default defineConfig(({ mode }) => {
  if (!(mode in APPS)) {
    throw new Error(`Use --mode admin or --mode public (got "${mode}").`);
  }
  const app = mode as AppName;
  const { devPort, backend } = APPS[app];

  return {
    root: srcDir(app),
    // Built files are served from the site root by FastAPI.
    base: "/",
    publicDir: false,
    plugins: [react(), ...(app === "public" ? [noAdminCode()] : [])],
    build: {
      outDir: fileURLToPath(new URL(`./dist/${app}/`, import.meta.url)),
      emptyOutDir: true,
    },
    server: {
      host: "127.0.0.1",
      port: devPort,
      strictPort: true,
      proxy: {
        "/api": {
          target: backend,
          // The backend's host guard answers only 127.0.0.1 / localhost.
          changeOrigin: true,
          // DEV ONLY. The page runs on the Vite port, so the browser sends
          // Origin: http://127.0.0.1:5173, and the backend's same-origin
          // check would refuse every POST. Vite and the backend together
          // stand in for one origin here, as FastAPI alone is in
          // production, so the proxy presents the backend's own origin.
          // Production has no Vite and no proxy: the real check applies.
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              if (proxyReq.getHeader("origin")) {
                proxyReq.setHeader("origin", backend);
              }
            });
          },
        },
      },
    },
  };
});

// Fails the public build if any module under src/admin ends up in it.
// ESLint warns about such imports in the editor; this is the check that
// can't be skipped, because it runs in every public build.
function noAdminCode(): Plugin {
  const adminDir = srcDir("admin").replaceAll("\\", "/");
  return {
    name: "no-admin-code-in-public-build",
    load(id) {
      if (id.replaceAll("\\", "/").startsWith(adminDir)) {
        this.error(`The public build must not include admin code: ${id}`);
      }
      return null;
    },
  };
}

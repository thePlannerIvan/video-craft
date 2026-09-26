import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "fs";
import { join } from "path";

const FEEDBACK_DIR = join(__dirname, "..", "feedback");

function safeId(value: unknown, fallback: string) {
  const raw = typeof value === "string" && value.trim() ? value : fallback;
  return raw.replace(/[^a-zA-Z0-9_-]/g, "-");
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: "step-feedback-api",
      configureServer(server) {
        server.middlewares.use("/api/storyboard-feedback", (req, res) => {
          if (req.method !== "POST") {
            res.writeHead(405);
            res.end();
            return;
          }
          let body = "";
          req.on("data", (chunk) => (body += chunk));
          req.on("end", () => {
            try {
              const payload = JSON.parse(body);
              mkdirSync(FEEDBACK_DIR, { recursive: true });
              const entry = {
                ...payload,
                phase: "storyboard",
                status: payload.status || "open",
                createdAt: new Date().toISOString(),
              };
              writeFileSync(join(FEEDBACK_DIR, "storyboard.jsonl"), `${JSON.stringify(entry)}\n`, {
                flag: "a",
              });
              res.writeHead(200, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ ok: true }));
            } catch {
              res.writeHead(400, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ ok: false }));
            }
          });
        });

        server.middlewares.use("/api/feedback", (req, res) => {
          if (req.method === "POST") {
            let body = "";
            req.on("data", (chunk) => (body += chunk));
            req.on("end", () => {
              try {
                const payload = JSON.parse(body);
                const chapterId = safeId(payload.chapterId, "unknown");
                mkdirSync(FEEDBACK_DIR, { recursive: true });
                const file = join(FEEDBACK_DIR, `${chapterId}.jsonl`);
                const entry = {
                  ...payload,
                  chapterId,
                  status: payload.status || "open",
                  createdAt: new Date().toISOString(),
                };
                writeFileSync(file, `${JSON.stringify(entry)}\n`, { flag: "a" });
                res.writeHead(200, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ ok: true }));
              } catch {
                res.writeHead(400, { "Content-Type": "application/json" });
                res.end(JSON.stringify({ ok: false }));
              }
            });
            return;
          }

          if (req.method === "GET") {
            const url = new URL(req.url!, "http://localhost");
            const chapterId = url.searchParams.get("chapter") || "";
            if (chapterId === "all") {
              if (!existsSync(FEEDBACK_DIR)) {
                res.writeHead(200, { "Content-Type": "application/x-ndjson" });
                res.end("");
                return;
              }
              const files = readdirSync(FEEDBACK_DIR).filter((f: string) => f.endsWith(".jsonl"));
              const allLines = files.map((f: string) => {
                try { return readFileSync(join(FEEDBACK_DIR, f), "utf-8"); }
                catch { return ""; }
              }).filter(Boolean).join("");
              res.writeHead(200, { "Content-Type": "application/x-ndjson" });
              res.end(allLines);
              return;
            }
            if (!chapterId) {
              res.writeHead(400, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ ok: false, error: "missing chapter" }));
              return;
            }
            const file = join(FEEDBACK_DIR, `${chapterId}.jsonl`);
            res.writeHead(200, { "Content-Type": "application/x-ndjson" });
            res.end(existsSync(file) ? readFileSync(file, "utf-8") : "");
            return;
          }

          res.writeHead(405);
          res.end();
        });
      },
    },
  ],
  server: {
    port: 5174,
    fs: { allow: [".."] },
  },
});

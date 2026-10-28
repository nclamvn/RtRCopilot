// Deterministic entry/import and built-route audit. No network or credential I/O.
import {readFile, realpath} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import crypto from "node:crypto";
import ts from "typescript";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const appsRoot = path.dirname(packageRoot);
const ownSource = path.join(packageRoot, "src");
const sharedSource = path.join(appsRoot, "web/src/workspace");
const sharedBff = path.join(appsRoot, "web/src/app/api/workspace/[[...path]]/route.ts");
const entries = ["src/app/layout.tsx", "src/app/page.tsx", "src/app/workspace/page.tsx", "src/app/api/workspace/[[...path]]/route.ts"];
const seen = new Map();
const external = new Set();

function permitted(file) {
  return file.startsWith(ownSource + path.sep) || file.startsWith(sharedSource + path.sep) || file === sharedBff;
}
async function resolveLocal(parent, specifier) {
  const bare = path.resolve(path.dirname(parent), specifier);
  for (const candidate of [bare, ...[".ts", ".tsx", ".css", "/index.ts", "/index.tsx"].map(ext => bare + ext)]) {
    try {return await realpath(candidate);} catch { /* Try a supported source extension. */ }
  }
  throw new Error(`Unresolved local import in ${path.relative(appsRoot, parent)}`);
}
async function visit(file) {
  file = await realpath(file);
  if (!permitted(file)) throw new Error(`Legacy/non-neutral source entered graph: ${path.relative(appsRoot, file)}`);
  if (seen.has(file)) return;
  const content = await readFile(file, "utf8");
  seen.set(file, crypto.createHash("sha256").update(content).digest("hex"));
  const imports = [];
  if (file.endsWith(".css")) {
    // Existing neutral CSS has no remote imports/fonts; fail rather than fetch.
    if (/@import\b|url\(\s*["']?\s*(?:https?:|\/\/)/i.test(content)) throw new Error("Remote CSS import/font forbidden");
    return;
  }
  const tree = ts.createSourceFile(file, content, ts.ScriptTarget.Latest, true);
  function walk(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) imports.push(node.moduleSpecifier.text);
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
      if (node.arguments.length !== 1 || !ts.isStringLiteral(node.arguments[0])) throw new Error("Dynamic unbounded source import forbidden");
      imports.push(node.arguments[0].text);
    }
    ts.forEachChild(node, walk);
  }
  walk(tree);
  for (const specifier of imports) {
    if (specifier.startsWith(".")) await visit(await resolveLocal(file, specifier));
    else {
      if (!["react", "react/jsx-runtime", "next", "next/navigation", "next/server"].includes(specifier)) throw new Error(`Unexpected package in neutral graph: ${specifier}`);
      external.add(specifier);
    }
  }
}
for (const entry of entries) await visit(path.join(packageRoot, entry));

let builtRoutes = null;
try {
  const manifest = JSON.parse(await readFile(path.join(packageRoot, ".next-build/server/app-paths-manifest.json"), "utf8"));
  builtRoutes = Object.keys(manifest).sort();
  const allowed = new Set(["/page", "/workspace/page", "/api/workspace/[[...path]]/route", "/_not-found/page", "/_global-error/page"]);
  if (builtRoutes.some(route => !allowed.has(route))) throw new Error("Unexpected legacy route in independent build");
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
console.log(JSON.stringify({status: "PASS", external_model_calls: 0,
  source_files: [...seen].map(([file, sha256]) => ({path: path.relative(appsRoot, file), sha256})),
  allowed_package_imports: [...external].sort(), built_routes: builtRoutes,
  excludes: ["legacy app layout/styles/proxy/auth", "company services/corpus", "remote CSS/fonts"],
  limitation: "Static source imports and compiled route manifest, not a transitive dependency/license audit or AI-quality certification. Shared neutral source remains in the monorepo."
}, null, 2));

import type {NextConfig} from "next";
import path from "node:path";

const config: NextConfig = {
  poweredByHeader: false,
  // One fixed reusable build directory. Dev keeps the ordinary .next directory.
  distDir: process.env.WORKSPACE_PRODUCTION_BUILD === "1" ? ".next-build" : ".next",
  outputFileTracingRoot: path.resolve(process.cwd(), "../.."),
  turbopack: {root: path.resolve(process.cwd(), "../..")},
};

export default config;

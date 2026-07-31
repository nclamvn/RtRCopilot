import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  skipProxyUrlNormalize: true,
};

export default nextConfig;

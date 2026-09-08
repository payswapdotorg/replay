import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // CDP bridge endpoints run python helpers; keep long-running screenshot calls allowed
  serverExternalPackages: [],
  async rewrites() {
    return [];
  },
};

export default nextConfig;

import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // package.json and node_modules live one level up, in the Speeds folder
  turbopack: { root: path.join(__dirname, "..") },
  outputFileTracingRoot: path.join(__dirname, ".."),
};

export default nextConfig;

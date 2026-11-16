import type { NextConfig } from "next";
import path from "node:path";

const onVercel = Boolean(process.env.VERCEL);
const repoRoot = path.join(__dirname, "..");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  devIndicators: false, // no Next.js "N" badge over the race card
  // node:sqlite is only used on the PC; keep it external so a Vercel build does not try to bundle it
  serverExternalPackages: ["node:sqlite"],
  // package.json and node_modules live one level up when running from the Speeds folder
  ...(onVercel
    ? {}
    : {
        turbopack: { root: repoRoot },
        outputFileTracingRoot: repoRoot,
      }),
};

export default nextConfig;

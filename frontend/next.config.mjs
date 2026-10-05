/** @type {import('next').NextConfig} */
const nextConfig = {
  // Docker copies the standalone server instead of the full node_modules tree.
  output: "standalone",
};

export default nextConfig;

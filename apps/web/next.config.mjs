/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@amc/shared", "@amc/config", "@amc/constants", "@amc/errors", "@amc/logger"],
};

export default nextConfig;

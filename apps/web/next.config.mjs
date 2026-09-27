/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@amc/shared"],
  allowedDevOrigins: process.env.BASE44_PUBLIC_HOST_SUFFIX
    ? ["https://3000-" + process.env.BASE44_PUBLIC_HOST_SUFFIX]
    : [],
};

export default nextConfig;

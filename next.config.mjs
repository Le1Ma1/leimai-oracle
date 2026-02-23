/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  experimental: {
    typedRoutes: true
  },
  async redirects() {
    return [
      {
        source: "/favicon.ico",
        destination: "/logo.png",
        permanent: true
      }
    ];
  }
};

export default nextConfig;

import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'lh3.googleusercontent.com',
        pathname: '/**',
      },
      {
        protocol: 'https',
        hostname: '*.ngrok-free.app',
        pathname: '/**',
      },
      {
        protocol: 'https',
        hostname: '*.ngrok.io',
        pathname: '/**',
      },
    ],
    formats: ['image/avif', 'image/webp'],
    minimumCacheTTL: 31536000,
  },
  experimental: {
    // CSS chunking for better parallel loading
    cssChunking: 'strict',
  },
  webpack: (config) => {
    // WASM 지원 (배경 제거 WASM 모델)
    config.experiments = { ...config.experiments, asyncWebAssembly: true }
    return config
  },
  compress: true,
  poweredByHeader: false,
};

export default nextConfig;

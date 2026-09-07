import type { NextConfig } from 'next';
import { LEGACY_ROUTE_REDIRECTS } from './lib/routes';

const nextConfig: NextConfig = {
  async redirects() {
    return LEGACY_ROUTE_REDIRECTS.map(({ source, destination }) => ({
      source,
      destination,
      permanent: false,
    }));
  },
};

export default nextConfig;

/** @type {import('next').NextConfig} */

// Internal Docker service hostname (used by the Next.js Node process for proxying,
// never exposed to the browser).
const BACKEND_INTERNAL = process.env.BACKEND_URL || 'http://backend:8000'

const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',

  // Proxy all /api/v1/* calls through Next.js so the browser always calls the
  // same origin regardless of whether the user is on localhost or Tailscale.
  // The browser → Next.js call is same-origin (no CORS).
  // The Next.js server → backend call is internal (Docker network, no CORS).
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        destination: `${BACKEND_INTERNAL}/api/v1/:path*`,
      },
    ]
  },
}

module.exports = nextConfig

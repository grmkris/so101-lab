import { createStartHandler, defaultStreamHandler } from '@tanstack/react-start/server'
import { apiHandler } from '#/api/live'

const startFetch = createStartHandler(defaultStreamHandler)

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url)
    if (url.pathname === '/api' || url.pathname.startsWith('/api/')) {
      return apiHandler(request)
    }
    return startFetch(request)
  },
}

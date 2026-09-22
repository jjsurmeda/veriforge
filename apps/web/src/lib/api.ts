import { client } from '../generated/client.gen'
import { authedFetch } from './auth'

// Same-origin (vite proxy in dev) with the auth/refresh fetch wrapper.
client.setConfig({ baseUrl: '', fetch: authedFetch })

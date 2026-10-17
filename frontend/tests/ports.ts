// Overrides keep local verification separate from an existing manual test session.
function port(name: string, fallback: number): number {
  const value = process.env[name]
  if (value === undefined) return fallback
  if (!/^[0-9]{1,5}$/u.test(value) || Number(value) < 1024 || Number(value) > 65535) throw new Error(`Invalid loopback test port: ${name}`)
  return Number(value)
}
export const apiPort = port('REGINTEL_TEST_API_PORT', 8000)
export const webPort = port('REGINTEL_TEST_WEB_PORT', 5173)
if (apiPort === webPort) throw new Error('Browser and API test ports must be distinct')
export const apiOrigin = `http://127.0.0.1:${apiPort}`
export const webOrigin = `http://127.0.0.1:${webPort}`

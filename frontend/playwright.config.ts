import { defineConfig, devices } from '@playwright/test'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'

const origin = 'http://127.0.0.1:5173'
const projectRoot = resolve(import.meta.dirname, '..')
const localUv = join(projectRoot, '.tools', 'uv', process.platform === 'win32' ? 'uv.exe' : 'uv')
const uvCommand = existsSync(localUv) ? `"${localUv}"` : 'uv'
const backendDirectory = join(projectRoot, 'backend')

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : 2,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: origin,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${uvCommand} run --project "${backendDirectory}" --locked --no-sync --offline --no-python-downloads uvicorn regintel.main:app --host 127.0.0.1 --port 8000`,
      url: 'http://127.0.0.1:8000/health/live',
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        REGINTEL_ENVIRONMENT: 'test',
        UV_CACHE_DIR: join(projectRoot, '.cache', 'uv'),
        UV_PYTHON_INSTALL_DIR: join(projectRoot, '.tools', 'python'),
        UV_PYTHON_DOWNLOADS: 'never',
      },
    },
    {
      command: 'pnpm dev',
      url: origin,
      reuseExistingServer: false,
      timeout: 30_000,
      env: { VITE_API_BASE_URL: 'http://127.0.0.1:8000' },
    },
  ],
})

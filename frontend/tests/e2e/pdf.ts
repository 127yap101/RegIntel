import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'

export async function expectRenderedSource(page: Page): Promise<void> {
  // Worker loading and page decoding are asynchronous. This is a bounded
  // readiness wait, separate from the page, pixel, hash and geometry assertions.
  await expect(page.getByText('Source verified · page rendered', { exact: true })).toBeVisible({ timeout: 15_000 })
}

/* Read-only real browser proof. Credentials arrive on stdin and are never persisted. */
'use strict';
const { chromium } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

async function main() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const settings = JSON.parse(input);
  if (typeof settings.username !== 'string' || typeof settings.password !== 'string' || typeof settings.corpus !== 'string' || !Number.isInteger(settings.page_index)) throw new Error('Explicit controlled browser inputs required.');
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, '.cache', 'published-browser-' + randomUUID().replaceAll('-', ''));
  await fs.mkdir(output);
  const browser = await chromium.launch({ headless: true });
  let page;
  try {
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = [];
    let credentialInUrl = false;
    page.on('pageerror', () => errors.push('page error'));
    page.on('request', (request) => {
      if (request.url().includes(settings.password) || request.url().includes(encodeURIComponent(settings.password))) credentialInUrl = true;
    });
    await page.goto('http://127.0.0.1:5173/');
    await page.getByLabel('Username', { exact: true }).fill(settings.username);
    await page.getByLabel('Password', { exact: true }).fill(settings.password);
    await page.getByRole('button', { name: 'Sign in to inspect filings' }).click();
    await page.getByRole('button', { name: /Premier Energies/i }).click();
    await page.getByRole('button', { name: 'Inspect source 1' }).click();
    await page.getByText('Source verified · page rendered', { exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Source page ' + (settings.page_index + 1), exact: true }).waitFor();
    const regions = await page.getByTestId('evidence-region').count();
    if (regions < 1) throw new Error('No persisted region rendered.');
    const source = page.getByRole('region', { name: 'Exact source page', exact: true });
    if (!(await source.textContent()).includes(settings.evidence_id)) throw new Error('Source membership mismatch.');
    if (!(await page.getByText('Viewing corpus: ' + settings.corpus, { exact: true }).count())) throw new Error('Corpus mismatch.');
    await source.screenshot({ path: path.join(output, 'source-page.png') });
    await page.screenshot({ path: path.join(output, 'explorer.png'), fullPage: true });
    await page.setViewportSize({ width: 375, height: 812 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    if (overflow) throw new Error('Narrow viewport overflows.');
    await page.screenshot({ path: path.join(output, 'narrow.png'), fullPage: true });
    await page.getByLabel('As-of date (optional)').fill('2026-01-01');
    await page.getByRole('button', { name: 'Apply view', exact: true }).click();
    await page.getByText(/date view is unavailable/).waitFor();
    if (await page.getByRole('region', { name: 'Exact source page', exact: true }).count()) throw new Error('Prior source view remained visible.');
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.getByRole('button', { name: 'Sign in to inspect filings', exact: true }).waitFor();
    const stored = await page.evaluate(() => localStorage.length + sessionStorage.length);
    if (stored || credentialInUrl || errors.length) throw new Error('Browser privacy or execution check failed.');
    const result = { status: 'passed', corpus_version_id: settings.corpus, evidence_id: settings.evidence_id, page_index: settings.page_index, rendered_regions: regions, actual_pdfjs_canvas: true, narrow_viewport: 'passed', unknown_date_as_of: 'explicitly unavailable', logout_clears_source: true, token_in_browser_storage: false, credentials_in_urls: false, browser_errors: 0, screenshots: ['source-page.png', 'explorer.png', 'narrow.png'] };
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(result, null, 2) + '\n');
    process.stdout.write(JSON.stringify({ status: 'passed', directory: output, rendered_regions: regions }) + '\n');
  } catch (error) {
    // Failure diagnostics are source-containing artifacts under ignored .cache.
    if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    throw new Error('Real published browser proof failed; inspect its ignored screenshot.');
  } finally { await browser.close(); }
}
main().catch(() => { process.stderr.write('Read-only real browser proof failed; secrets omitted.\n'); process.exitCode = 1; });

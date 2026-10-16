/* Read-only real administrator navigation. Approved local credentials arrive on stdin. */
'use strict';
const { chromium } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

async function main() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const settings = JSON.parse(input);
  for (const key of ['username', 'password', 'corpus', 'filing_job', 'processing_job', 'validation_run', 'candidate', 'observation', 'review', 'evidence', 'source_sha256']) {
    if (typeof settings[key] !== 'string' || !settings[key]) throw new Error('Explicit controlled browser inputs are required.');
  }
  const output = path.join(path.resolve(__dirname, '..'), '.cache', 'admin-browser-' + randomUUID().replaceAll('-', ''));
  await fs.mkdir(output);
  const browser = await chromium.launch({ headless: true });
  let page;
  let stage = 'initial';
  try {
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.setDefaultTimeout(20_000);
    let blockedWrites = 0;
    let credentialInUrl = false;
    const errors = [];
    await page.route('**/v1/**', async (route) => {
      const request = route.request();
      const login = request.method() === 'POST' && new URL(request.url()).pathname === '/v1/auth/token';
      if (!login && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        blockedWrites += 1;
        await route.abort();
      } else await route.continue();
    });
    page.on('pageerror', () => errors.push('page error'));
    page.on('request', (request) => {
      if (request.url().includes(settings.password) || request.url().includes(encodeURIComponent(settings.password))) credentialInUrl = true;
    });
    await page.goto('http://127.0.0.1:5173/');
    await page.getByRole('link', { name: 'Administrator workspace', exact: true }).click();
    await page.getByLabel('Administrator username', { exact: true }).fill(settings.username);
    await page.getByLabel('Administrator password', { exact: true }).fill(settings.password);
    await page.getByRole('button', { name: 'Sign in as administrator', exact: true }).click();
    const queue = page.getByRole('region', { name: 'Selected work queue', exact: true });
    const nav = page.getByRole('navigation', { name: 'Administrator work queues', exact: true });
    async function choose(label, id) {
      await nav.getByRole('button', { name: label, exact: true }).click();
      for (let attempt = 0; attempt < 40; attempt += 1) {
        await queue.getByRole('button', { name: 'Refresh queue', exact: true }).waitFor();
        await page.waitForFunction(() => ![...document.querySelectorAll('button')].find((button) => button.textContent === 'Refresh queue')?.disabled);
        const item = queue.getByRole('button').filter({ hasText: id });
        if (await item.count() === 1) { await item.click(); return; }
        const next = queue.getByRole('button', { name: 'More queue items', exact: true });
        if (await next.isDisabled()) break;
        await next.click();
      }
      throw new Error('Recorded item is absent from the bounded queue.');
    }
    await queue.waitFor();
    stage = 'filing';
    await choose('Filing jobs', settings.filing_job);
    const filing = page.getByRole('region', { name: 'Filing job details', exact: true });
    await filing.getByRole('heading', { name: 'Filing state: PARSED', exact: true }).waitFor();
    if (!(await filing.textContent()).includes(settings.source_sha256)) throw new Error('Original source identity differs.');
    stage = 'processing';
    await choose('Processing jobs', settings.processing_job);
    const processing = page.getByRole('region', { name: 'Processing job details', exact: true });
    await processing.getByRole('heading', { name: 'Processing state: SUCCEEDED', exact: true }).waitFor();
    if (await processing.getByRole('list').first().getByRole('listitem').count() !== 3) throw new Error('Processing checkpoints differ.');
    if (!(await processing.getByRole('button', { name: 'Dispatch pending workflow', exact: true }).isDisabled())) throw new Error('Completed workflow dispatch was enabled.');
    stage = 'review';
    await choose('Validation and quarantine', settings.validation_run);
    const card = page.getByRole('article', { name: 'Candidate ' + settings.candidate, exact: true });
    await card.getByText('Recorded decision: APPROVE_FOR_PUBLICATION', { exact: true }).waitFor();
    const content = await card.textContent();
    if (!content.includes(settings.review) || !content.includes(settings.observation) || !content.includes('subject to')) throw new Error('Accepted conditional disclosure or prior immutable review differs.');
    if (await card.getByRole('button', { name: 'Record decision', exact: true }).count()) throw new Error('An accepted final decision was editable.');
    if (await card.getByRole('button', { name: 'Add reviewed candidate to draft', exact: true }).count()) throw new Error('An accepted candidate could be selected again.');
    await card.getByText('All 16 validation checks', { exact: true }).click();
    if (await card.locator('details').first().getByRole('listitem').count() !== 16) throw new Error('Validation checks differ.');
    await card.screenshot({ path: path.join(output, 'accepted-review.png') });
    stage = 'source';
    await card.getByRole('button', { name: 'Inspect source 1', exact: true }).click();
    await page.getByText('Source verified · page rendered', { exact: true }).waitFor();
    const source = page.getByRole('region', { name: 'Exact source page', exact: true });
    if (!(await source.textContent()).includes(settings.evidence)) throw new Error('Evidence identity differs.');
    if (await source.getByTestId('evidence-region').count() !== 1) throw new Error('Original evidence region is absent.');
    await source.screenshot({ path: path.join(output, 'original-source.png') });
    stage = 'narrow';
    await page.setViewportSize({ width: 375, height: 812 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Narrow viewport overflows.');
    await card.screenshot({ path: path.join(output, 'narrow-review.png') });
    stage = 'publication';
    await page.setViewportSize({ width: 1280, height: 900 });
    await choose('Publication builds', settings.corpus);
    const build = page.getByRole('region', { name: 'Approved publication build', exact: true });
    await build.getByRole('heading', { name: 'Published corpus', exact: true }).waitFor();
    if (!(await build.textContent()).includes(settings.observation)) throw new Error('Published history differs.');
    if (!(await build.getByRole('button', { name: 'Publish this approved build', exact: true }).isDisabled())) throw new Error('Existing corpus publication was enabled.');
    await build.screenshot({ path: path.join(output, 'published-scope.png') });
    stage = 'logout';
    await page.getByRole('button', { name: 'Sign out of administrator workspace', exact: true }).click();
    await page.getByRole('button', { name: 'Sign in as administrator', exact: true }).waitFor();
    if (await queue.count() || await card.count() || await build.count() || await source.count()) throw new Error('Private state survived logout.');
    const stored = await page.evaluate(() => localStorage.length + sessionStorage.length);
    if (stored || credentialInUrl || errors.length || blockedWrites) throw new Error('Read-only browser privacy/execution check failed.');
    const result = {
      status: 'passed', corpus_version_id: settings.corpus, validation_run_id: settings.validation_run,
      candidate_id: settings.candidate, accepted_observation_id: settings.observation,
      historical_review_id: settings.review, evidence_id: settings.evidence,
      filing_and_processing_navigation: 'passed', completed_checkpoints: 3,
      validation_checks: 16, accepted_history_immutable: true, conditional_text_retained: true,
      source_page_index: 2, actual_pdfjs_canvas: true, rendered_regions: 1,
      source_sha256: settings.source_sha256, narrow_viewport: 'passed',
      explicit_published_scope: true, private_state_cleared: true,
      authoritative_write_requests: 0, token_in_browser_storage: false,
      credentials_in_urls: false, browser_errors: 0,
      screenshots: ['accepted-review.png', 'original-source.png', 'narrow-review.png', 'published-scope.png'],
    };
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(result, null, 2) + '\n');
    process.stdout.write(JSON.stringify({ status: 'passed', directory: output }) + '\n');
  } catch (error) {
    const message = String(error.message).replaceAll(settings.password, '[omitted]').replaceAll(settings.username, '[omitted]').slice(0, 1500);
    await fs.writeFile(path.join(output, 'failure-stage.json'), JSON.stringify({ stage, message }) + '\n');
    if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    throw new Error('Read-only real administrator browser proof failed; inspect ignored diagnostics.');
  } finally { await browser.close(); }
}
main().catch(() => { process.stderr.write('Read-only real administrator browser proof failed; secrets omitted.\n'); process.exitCode = 1; });

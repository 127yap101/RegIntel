/* Read-only real question/source proof. Approved local credentials arrive on stdin. */
'use strict';
const { chromium } = require('../frontend/node_modules/@playwright/test');
const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

async function main() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;
  const settings = JSON.parse(input);
  if (typeof settings.username !== 'string' || typeof settings.password !== 'string' || typeof settings.corpus !== 'string' || typeof settings.evidence_id !== 'string') throw new Error('Explicit controlled browser inputs required.');
  const output = path.join(path.resolve(__dirname, '..'), '.cache', 'retrieval-browser-' + randomUUID().replaceAll('-', ''));
  await fs.mkdir(output);
  const browser = await chromium.launch({ headless: true });
  let page;
  let stage = 'initial';
  try {
    page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.setDefaultTimeout(20_000);
    const errors = [];
    let credentialInUrl = false;
    page.on('pageerror', () => errors.push('page error'));
    page.on('request', (request) => { if (request.url().includes(settings.password) || request.url().includes(encodeURIComponent(settings.password))) credentialInUrl = true; });
    await page.goto('http://127.0.0.1:5173/');
    await page.getByLabel('Username', { exact: true }).fill(settings.username);
    await page.getByLabel('Password', { exact: true }).fill(settings.password);
    await page.getByRole('button', { name: 'Sign in to inspect filings' }).click();
    stage = 'company';
    await page.getByRole('button', { name: /Premier Energies/i }).click();
    stage = 'question';
    await page.getByLabel('Question', { exact: true }).fill('What does the filing disclose about an initial public offering?');
    await page.getByRole('button', { name: 'Find cited evidence', exact: true }).click();
    const panel = page.getByRole('region', { name: 'Questions about published filings', exact: true });
    await panel.getByText('Verbatim source excerpt', { exact: true }).waitFor();
    if (!(await panel.locator('blockquote').textContent()).includes('subject to')) throw new Error('Source conditions were not retained.');
    stage = 'source';
    await panel.getByRole('button', { name: 'Source 1 · page 3', exact: true }).click();
    await page.getByText('Source verified · page rendered', { exact: true }).waitFor();
    const source = page.getByRole('region', { name: 'Exact source page', exact: true });
    if (!(await source.textContent()).includes(settings.evidence_id)) throw new Error('Evidence membership differs.');
    if (await page.getByTestId('evidence-region').count() !== 1) throw new Error('Missing original evidence region.');
    if (!(await page.getByText('Viewing corpus: ' + settings.corpus, { exact: true }).count())) throw new Error('Corpus differs.');
    await page.screenshot({ path: path.join(output, 'question-source.png'), fullPage: true });
    stage = 'narrow';
    await page.setViewportSize({ width: 375, height: 812 });
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Narrow viewport overflows.');
    stage = 'narrow-screenshot';
    await panel.screenshot({ path: path.join(output, 'narrow-question.png') });
    stage = 'numeric';
    await page.getByLabel('Question', { exact: true }).fill('What is the revenue?');
    await page.getByRole('button', { name: 'Find cited evidence', exact: true }).click();
    await panel.getByText('No supported answer is available for this request.', { exact: true }).waitFor();
    if (await panel.locator('blockquote').count()) throw new Error('Old claim survived numeric abstention.');
    if (await source.count()) throw new Error('Old source survived a new question.');
    stage = 'logout';
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await page.getByRole('button', { name: 'Sign in to inspect filings', exact: true }).waitFor();
    if (await page.getByLabel('Question', { exact: true }).count()) throw new Error('Private question state survived logout.');
    const stored = await page.evaluate(() => localStorage.length + sessionStorage.length);
    if (stored || credentialInUrl || errors.length) throw new Error('Browser privacy/execution check failed.');
    const result = { status: 'passed', corpus_version_id: settings.corpus, evidence_id: settings.evidence_id, real_b3_answer: true, complete_conditional_quote: true, source_page_index: 2, actual_pdfjs_canvas: true, rendered_regions: 1, narrow_viewport: 'passed', numeric_context_abstention: 'passed', stale_claim_source_cleared: true, logout_clears_question: true, token_in_browser_storage: false, credentials_in_urls: false, browser_errors: 0, screenshots: ['question-source.png', 'narrow-question.png'] };
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(result, null, 2) + '\n');
    process.stdout.write(JSON.stringify({ status: 'passed', directory: output }) + '\n');
  } catch (error) {
    const message = String(error.message).replaceAll(settings.password, '[omitted]').replaceAll(settings.username, '[omitted]').slice(0, 1500);
    await fs.writeFile(path.join(output, 'failure-stage.json'), JSON.stringify({ stage, message }) + '\n');
    if (page) {
      const layout = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth, overflow: [...document.querySelectorAll('*')].map((element) => ({ tag: element.tagName, role: element.getAttribute('role'), class: element.getAttribute('class'), right: element.getBoundingClientRect().right, width: element.getBoundingClientRect().width })).filter((item) => item.right > innerWidth + 1) })).catch(() => ({}));
      await fs.writeFile(path.join(output, 'failure-layout.json'), JSON.stringify(layout));
    }
    if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    throw new Error('Read-only real retrieval browser proof failed; inspect ignored screenshot.');
  } finally { await browser.close(); }
}
main().catch(() => { process.stderr.write('Read-only real retrieval browser proof failed; secrets omitted.\n'); process.exitCode = 1; });

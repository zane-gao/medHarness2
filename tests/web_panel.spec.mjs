import { test, expect } from '@playwright/test';

const pageUrl = new URL('../web/index.html', import.meta.url).href;
const sections = ['what', 'flow', 'arch', 'wf', 'tools', 'run', 'fresh', 'map', 'issues'];

for (const viewport of [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`status dashboard ${viewport.name}`, async ({ page }) => {
    const consoleErrors = [];
    page.on('console', message => {
      if (message.type() === 'error') consoleErrors.push(message.text());
    });
    page.on('pageerror', error => consoleErrors.push(String(error)));
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(pageUrl);
    await expect(page.locator('#project-meta-strip')).toContainText('pilot_only');
    for (const id of sections) await expect(page.locator(`#${id}`)).toBeVisible();
    await page.locator('a[href="#issues"]').first().click();
    await expect(page.locator('#issues')).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
    expect(consoleErrors).toEqual([]);
    await page.screenshot({ path: `test-results/web-panel-${viewport.name}.png`, fullPage: true });
  });
}

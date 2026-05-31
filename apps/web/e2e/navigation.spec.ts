import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
  test('home page loads with correct title', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('Astraeus — Operator Terminal');
    await expect(page.getByText('Astraeus Operator Terminal')).toBeVisible();
  });

  test('sidebar navigation works', async ({ page }) => {
    await page.goto('/');

    // Navigate to recommendations
    await page.getByRole('link', { name: 'Approve' }).click();
    await expect(page.getByText('Recommendations')).toBeVisible();

    // Navigate to orders
    await page.getByRole('link', { name: 'Orders' }).click();
    await expect(page.getByText('Order Book')).toBeVisible();

    // Navigate to kill switch
    await page.getByRole('link', { name: 'Kill Switch' }).click();
    await expect(page.getByText('Kill Switches')).toBeVisible();
  });

  test('command palette opens with Ctrl+K', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Control+k');
    await expect(page.getByPlaceholder('Type a command or search...')).toBeVisible();
  });

  test('command palette closes with Escape', async ({ page }) => {
    await page.goto('/');
    await page.keyboard.press('Control+k');
    await expect(page.getByPlaceholder('Type a command or search...')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByPlaceholder('Type a command or search...')).not.toBeVisible();
  });

  test('status bar shows connection state', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('Disconnected')).toBeVisible();
  });
});

test.describe('Kill Switch', () => {
  test('displays all scopes', async ({ page }) => {
    await page.goto('/kill-switch');
    await expect(page.getByText('global')).toBeVisible();
    await expect(page.getByText('account:alpaca-paper-1')).toBeVisible();
    await expect(page.getByText('strategy:momentum_xs')).toBeVisible();
  });

  test('arm button requires reason', async ({ page }) => {
    await page.goto('/kill-switch');
    // Arm buttons should be disabled without reason
    const armButtons = page.getByRole('button', { name: 'Arm' });
    const firstArm = armButtons.first();
    await expect(firstArm).toBeDisabled();

    // Fill reason
    await page.getByPlaceholder('e.g. maintenance window').fill('test reason');
    await expect(firstArm).toBeEnabled();
  });
});

test.describe('Recommendations', () => {
  test('page loads with date and empty state', async ({ page }) => {
    await page.goto('/approve');
    await expect(page.getByText('Recommendations')).toBeVisible();
    await expect(page.getByText('Pipeline Output')).toBeVisible();
    await expect(page.getByText('Decision')).toBeVisible();
  });
});

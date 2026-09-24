import { expect, test } from '@jupyterlab/galata';

const PLUGIN_ID =
  'jupyterlab_kernel_terminal_workspace_culler_extension:plugin';
const STATUS_URL =
  '/jupyterlab-kernel-terminal-workspace-culler-extension/status';

test.describe('activation', () => {
  /**
   * Don't load JupyterLab webpage before running the tests.
   * This is required to ensure we capture all log messages.
   */
  test.use({ autoGoto: false });

  test('should emit an activation console message', async ({ page }) => {
    const logs: string[] = [];

    page.on('console', message => {
      logs.push(message.text());
    });

    await page.goto();

    expect(
      logs.filter(
        s =>
          s ===
          'JupyterLab extension jupyterlab_kernel_terminal_workspace_culler_extension is activated!'
      )
    ).toHaveLength(1);
  });
});

test('settings editor shows the idle limits with their defaults', async ({
  page
}) => {
  await page.evaluate(async () => {
    await window.jupyterapp.commands.execute('settingeditor:open', {
      query: 'Resource Culler'
    });
  });

  // the settings form titles each field with a heading, not a <label>
  const field = (title: string) =>
    page
      .getByRole('heading', { name: title, exact: true })
      .locator('xpath=following::input[1]');

  await expect(field('Terminal Maximum Idle (minutes)')).toHaveValue('10080');
  await expect(field('Terminal Idle Timeout (minutes)')).toHaveValue('60');
  await expect(field('Workspace Idle Timeout (minutes)')).toHaveValue('10080');
});

test('a changed terminal maximum idle reaches the server', async ({ page }) => {
  await page.evaluate(async id => {
    const registry = await window.galata.getPlugin(
      '@jupyterlab/apputils-extension:settings'
    );
    await registry.set(id, 'terminalCullMaxIdleTimeout', 1440);
  }, PLUGIN_ID);

  await expect
    .poll(async () => {
      const response = await page.request.get(STATUS_URL);
      return (await response.json()).settings.terminalCullMaxIdleTimeout;
    })
    .toBe(1440);

  await page.evaluate(async id => {
    const registry = await window.galata.getPlugin(
      '@jupyterlab/apputils-extension:settings'
    );
    await registry.remove(id, 'terminalCullMaxIdleTimeout');
  }, PLUGIN_ID);
});

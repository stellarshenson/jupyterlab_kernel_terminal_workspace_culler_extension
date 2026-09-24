/**
 * Configuration for Playwright using default from @jupyterlab/galata
 *
 * Galata pins `c.ServerApp.port = 8888` with `port_retries = 0`, so the test
 * server fails to start while a developer's own lab holds that port.
 * `JUPYTER_TEST_PORT` threads one port through this config and
 * jupyter_server_test_config.py; CI leaves the default.
 *
 * A server is never reused: any lab on this machine answers this extension's
 * routes (the installed copy loads everywhere), so a reused lab cannot be told
 * apart from ours and the suite would test code that is not the working tree.
 * A taken port fails the run instead.
 */
const path = require('path');
const baseConfig = require('@jupyterlab/galata/lib/playwright-config');

const PORT = process.env.JUPYTER_TEST_PORT || '8888';
const BASE_URL = `http://localhost:${PORT}`;

module.exports = {
  ...baseConfig,
  use: { ...baseConfig.use, baseURL: BASE_URL },
  webServer: {
    command: 'jlpm start',
    url: `${BASE_URL}/lab`,
    timeout: 120 * 1000,
    reuseExistingServer: false,
    env: {
      // the server extension under test is the working tree, not an installed copy
      PYTHONPATH: path.resolve(__dirname, '..')
    }
  }
};

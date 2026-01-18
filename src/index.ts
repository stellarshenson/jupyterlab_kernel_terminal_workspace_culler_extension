import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

import { requestAPI } from './request';

// Store settings for notification check
let showNotifications = true;

/**
 * Sync settings to the backend culler.
 */
async function syncSettings(
  settings: ISettingRegistry.ISettings
): Promise<void> {
  const composite = settings.composite as Record<string, unknown>;
  showNotifications = (composite.showNotifications as boolean) ?? true;

  try {
    await requestAPI<{ status: string }>('settings', {
      method: 'POST',
      body: JSON.stringify(composite)
    });
  } catch (error) {
    console.error(
      '[Culler] Failed to sync settings to backend:',
      error
    );
  }
}

/**
 * Poll for cull results and show notifications if resources were culled.
 */
async function pollCullResults(app: JupyterFrontEnd): Promise<void> {
  try {
    const result = await requestAPI<{
      kernels_culled: string[];
      terminals_culled: string[];
      sessions_culled: string[];
    }>('cull-result');

    const kernelCount = result.kernels_culled?.length ?? 0;
    const terminalCount = result.terminals_culled?.length ?? 0;
    const sessionCount = result.sessions_culled?.length ?? 0;

    if (
      showNotifications &&
      (kernelCount > 0 || terminalCount > 0 || sessionCount > 0)
    ) {
      const lines: string[] = ['Idle resources culled:'];
      if (kernelCount > 0) {
        lines.push(`Kernels: ${kernelCount}`);
      }
      if (terminalCount > 0) {
        lines.push(`Terminals: ${terminalCount}`);
      }
      if (sessionCount > 0) {
        lines.push(`Sessions: ${sessionCount}`);
      }

      // Try to use jupyterlab-notifications-extension if available
      if (app.commands.hasCommand('jupyterlab-notifications:send')) {
        await app.commands.execute('jupyterlab-notifications:send', {
          message: lines.join('<br>'),
          type: 'info',
          autoClose: 5000
        });
      } else {
        // Fallback to console log
        console.info('[Culler]', lines.join(' | '));
      }
    }
  } catch {
    // Silently ignore - cull-result may return empty or server may be unavailable
  }
}

/**
 * Initialization data for the jupyterlab_kernel_terminal_workspace_culler_extension extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_kernel_terminal_workspace_culler_extension:plugin',
  description:
    'JupyterLab extension to automatically cull idle kernels, terminals, and sessions.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (
    app: JupyterFrontEnd,
    settingRegistry: ISettingRegistry | null
  ) => {
    console.log(
      'JupyterLab extension jupyterlab_kernel_terminal_workspace_culler_extension is activated!'
    );

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log(
            '[Culler] Settings loaded:',
            settings.composite
          );
          syncSettings(settings);
          settings.changed.connect(() => syncSettings(settings));
        })
        .catch(reason => {
          console.error(
            '[Culler] Failed to load settings:',
            reason
          );
        });
    }

    // Poll for cull results every 30 seconds
    setInterval(() => pollCullResults(app), 30000);
  }
};

export default plugin;

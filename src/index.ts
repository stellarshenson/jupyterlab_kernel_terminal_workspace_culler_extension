import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

import { ITerminalTracker } from '@jupyterlab/terminal';

import { requestAPI } from './request';

// Store settings for notification check and intervals
let showNotifications = true;
let cullCheckIntervalMinutes = 5; // default 5 minutes
let cullResultsIntervalId: ReturnType<typeof setInterval> | null = null;
let terminalReportIntervalId: ReturnType<typeof setInterval> | null = null;

/**
 * Sync settings to the backend culler and update local interval settings.
 */
async function syncSettings(
  settings: ISettingRegistry.ISettings,
  app: JupyterFrontEnd,
  terminalTracker: ITerminalTracker | null
): Promise<void> {
  const composite = settings.composite as Record<string, unknown>;
  showNotifications = (composite.showNotifications as boolean) ?? true;

  // Check if cullCheckInterval changed
  const newInterval = (composite.cullCheckInterval as number) ?? 5;
  const intervalChanged = newInterval !== cullCheckIntervalMinutes;
  cullCheckIntervalMinutes = newInterval;

  try {
    await requestAPI<{ status: string }>('settings', {
      method: 'POST',
      body: JSON.stringify(composite)
    });
  } catch (error) {
    console.error('[Culler] Failed to sync settings to backend:', error);
  }

  // Restart intervals if cullCheckInterval changed
  if (intervalChanged) {
    console.log(
      `[Culler] Cull check interval changed to ${cullCheckIntervalMinutes} minutes`
    );
    setupIntervals(app, terminalTracker);
  }
}

/**
 * Set up periodic intervals for cull results polling and terminal reporting.
 * Uses the configurable cullCheckInterval setting for both.
 */
function setupIntervals(
  app: JupyterFrontEnd,
  terminalTracker: ITerminalTracker | null
): void {
  const intervalMs = cullCheckIntervalMinutes * 60 * 1000;

  // Clear existing intervals
  if (cullResultsIntervalId !== null) {
    clearInterval(cullResultsIntervalId);
  }
  if (terminalReportIntervalId !== null) {
    clearInterval(terminalReportIntervalId);
  }

  // Set up cull results polling
  cullResultsIntervalId = setInterval(() => pollCullResults(app), intervalMs);

  // Set up terminal reporting (only if tracker is available)
  if (terminalTracker) {
    terminalReportIntervalId = setInterval(
      () => reportActiveTerminals(terminalTracker),
      intervalMs
    );
  }

  console.log(
    `[Culler] Intervals set to ${cullCheckIntervalMinutes} minutes (${intervalMs}ms)`
  );
}

/**
 * Poll for cull results and show notifications if resources were culled.
 */
async function pollCullResults(app: JupyterFrontEnd): Promise<void> {
  try {
    const result = await requestAPI<{
      kernels_culled: string[];
      terminals_culled: string[];
      workspaces_culled: string[];
    }>('cull-result');

    const kernelCount = result.kernels_culled?.length ?? 0;
    const terminalCount = result.terminals_culled?.length ?? 0;
    const workspaceCount = result.workspaces_culled?.length ?? 0;

    if (
      showNotifications &&
      (kernelCount > 0 || terminalCount > 0 || workspaceCount > 0)
    ) {
      const lines: string[] = ['Idle resources culled:'];
      if (kernelCount > 0) {
        lines.push(`Kernels: ${kernelCount}`);
      }
      if (terminalCount > 0) {
        lines.push(`Terminals: ${terminalCount}`);
      }
      if (workspaceCount > 0) {
        lines.push(`Workspaces: ${workspaceCount}`);
      }

      // Try to use jupyterlab-notifications-extension if available
      if (app.commands.hasCommand('jupyterlab-notifications:send')) {
        await app.commands.execute('jupyterlab-notifications:send', {
          message: lines.join('\n'),
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
 * Report active terminal tabs to the backend.
 * This enables the backend to distinguish between terminals with open tabs
 * and terminals whose tabs have been closed (for disconnected-only culling).
 */
async function reportActiveTerminals(tracker: ITerminalTracker): Promise<void> {
  const activeTerminals: string[] = [];

  tracker.forEach(widget => {
    // widget.content is the Terminal, widget.content.session.name is the terminal name
    // Check isAttached (has open tab) and !isDisposed, but NOT isVisible
    // isVisible is false when tab exists but another tab is selected
    const name = widget.content.session?.name;
    if (name && widget.isAttached && !widget.isDisposed) {
      activeTerminals.push(name);
    }
  });

  try {
    await requestAPI<{ status: string }>('active-terminals', {
      method: 'POST',
      body: JSON.stringify({ terminals: activeTerminals })
    });
  } catch (e) {
    console.debug('[Culler] Failed to report active terminals:', e);
  }
}

/**
 * Initialization data for the jupyterlab_kernel_terminal_workspace_culler_extension extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_kernel_terminal_workspace_culler_extension:plugin',
  description:
    'JupyterLab extension to automatically cull idle kernels, terminals, and workspaces.',
  autoStart: true,
  optional: [ISettingRegistry, ITerminalTracker],
  activate: (
    app: JupyterFrontEnd,
    settingRegistry: ISettingRegistry | null,
    terminalTracker: ITerminalTracker | null
  ) => {
    console.log(
      'JupyterLab extension jupyterlab_kernel_terminal_workspace_culler_extension is activated!'
    );

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('[Culler] Settings loaded:', settings.composite);

          // Get initial interval before setting up
          const composite = settings.composite as Record<string, unknown>;
          cullCheckIntervalMinutes =
            (composite.cullCheckInterval as number) ?? 5;

          // Sync settings to backend
          syncSettings(settings, app, terminalTracker);

          // Set up intervals with initial settings
          setupIntervals(app, terminalTracker);

          // Re-sync on settings change
          settings.changed.connect(() =>
            syncSettings(settings, app, terminalTracker)
          );
        })
        .catch(reason => {
          console.error('[Culler] Failed to load settings:', reason);
          // Use default interval if settings fail to load
          setupIntervals(app, terminalTracker);
        });
    } else {
      // No settings registry, use default interval
      setupIntervals(app, terminalTracker);
    }

    // Track active terminals via event handlers (immediate response to changes)
    if (terminalTracker) {
      // Report when terminal widgets change
      terminalTracker.currentChanged.connect(() => {
        reportActiveTerminals(terminalTracker);
      });

      // Also report when widgets are added/removed
      terminalTracker.widgetAdded.connect(() => {
        reportActiveTerminals(terminalTracker);
      });

      // Initial report
      reportActiveTerminals(terminalTracker);
    }
  }
};

export default plugin;

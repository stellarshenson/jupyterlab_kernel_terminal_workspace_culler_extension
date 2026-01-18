import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

import { requestAPI } from './request';

/**
 * Initialization data for the jupyterlab_kernel_terminal_workspace_culler_extension extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_kernel_terminal_workspace_culler_extension:plugin',
  description: 'Jupyterlab extension to kill unused kernels, terminals and workspaces. User can configure the idle time (minutes) after which the resource will be released automatically. This helps with the locked memory, insane number of terminals opened etc.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (app: JupyterFrontEnd, settingRegistry: ISettingRegistry | null) => {
    console.log('JupyterLab extension jupyterlab_kernel_terminal_workspace_culler_extension is activated!');

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('jupyterlab_kernel_terminal_workspace_culler_extension settings loaded:', settings.composite);
        })
        .catch(reason => {
          console.error('Failed to load settings for jupyterlab_kernel_terminal_workspace_culler_extension.', reason);
        });
    }

    requestAPI<any>('hello')
      .then(data => {
        console.log(data);
      })
      .catch(reason => {
        console.error(
          `The jupyterlab_kernel_terminal_workspace_culler_extension server extension appears to be missing.\n${reason}`
        );
      });
  }
};

export default plugin;

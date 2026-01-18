try:
    from ._version import __version__
except ImportError:
    # Fallback when using the package in dev mode without installing
    # in editable mode with pip. It is highly recommended to install
    # the package from a stable release or in editable mode: https://pip.pypa.io/en/stable/topics/local-project-installs/#editable-installs
    import warnings

    warnings.warn(
        "Importing 'jupyterlab_kernel_terminal_workspace_culler_extension' outside a proper installation."
    )
    __version__ = "dev"

from .culler import ResourceCuller
from .routes import set_culler, setup_route_handlers

# Global culler instance
_culler_instance: ResourceCuller | None = None


def get_culler() -> ResourceCuller | None:
    """Return the global culler instance."""
    return _culler_instance


def _jupyter_labextension_paths():
    return [{"src": "labextension", "dest": "jupyterlab_kernel_terminal_workspace_culler_extension"}]


def _jupyter_server_extension_points():
    return [{"module": "jupyterlab_kernel_terminal_workspace_culler_extension"}]


def _load_jupyter_server_extension(server_app):
    """Registers the API handler and starts the resource culler.

    Parameters
    ----------
    server_app: jupyterlab.labapp.LabApp
        JupyterLab application instance
    """
    global _culler_instance

    # Set up route handlers
    setup_route_handlers(server_app.web_app)

    # Create and start the culler
    _culler_instance = ResourceCuller(server_app)
    set_culler(_culler_instance)
    _culler_instance.start()

    name = "jupyterlab_kernel_terminal_workspace_culler_extension"
    server_app.log.info(f"Registered {name} server extension")
    server_app.log.info("[Culler] Resource culler initialized and started")

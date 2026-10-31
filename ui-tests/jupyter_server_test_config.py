"""Server configuration for integration tests.

!! Never use this configuration in production because it
opens the server to the world and provide access to JupyterLab
JavaScript objects through the global window variable.
"""
import os
import shutil
import sys
import tempfile

import jupyterlab.galata
from jupyterlab.galata import configure_jupyter_server

configure_jupyter_server(c)

# Match the port playwright.config.js waits on. `or`, not a get() default: an
# exported-but-empty JUPYTER_TEST_PORT would otherwise make int("") raise.
c.ServerApp.port = int(os.environ.get("JUPYTER_TEST_PORT") or "8888")

# Serve the working tree's labextension build (`jlpm build`) and nothing else.
# An installed copy of this extension would otherwise win or be the only one,
# and every other installed labextension would load into the test page too.
# Federated extensions are looked up by directory name, so the build is copied
# into a directory named after the package.
_PACKAGE = "jupyterlab_kernel_terminal_workspace_culler_extension"
_LABEXTENSION = "@stellarshenson/jupyterlab-kernel-terminal-workspace-culler-extension"
_BUILD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), _PACKAGE, "labextension"
)
# The CI job installs the wheel and has no working-tree build.
if not os.path.isdir(_BUILD):
    _BUILD = os.path.join(sys.prefix, "share", "jupyter", "labextensions", _LABEXTENSION)
_LABEXTENSIONS = tempfile.mkdtemp(prefix="culler-labextensions-")
shutil.copytree(_BUILD, os.path.join(_LABEXTENSIONS, _LABEXTENSION))
c.LabServerApp.labextensions_path = [
    _LABEXTENSIONS,
    os.path.dirname(os.path.abspath(jupyterlab.galata.__file__)),
]

# Galata deletes each test's folder through the contents API; a temp root has
# no trash the server may write to, so delete outright. Set on every concrete
# class: a site config that pins the subclasses to True outranks the base class.
for _manager in (
    "FileContentsManager",
    "AsyncFileContentsManager",
    "AsyncLargeFileManager",
    "AsyncJupytextContentsManager",
):
    c[_manager].delete_to_trash = False

# Uncomment to set server log level to debug level
# c.ServerApp.log_level = "DEBUG"

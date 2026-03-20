"""
Enterprise AI platform package.

NOTE: This package is named 'platform', which shadows the Python stdlib module of
the same name.  Third-party packages (httpx → zstandard, etc.) do `import platform`
expecting the stdlib module.  To prevent AttributeErrors, we load the stdlib module
by its absolute path and re-export its public API here.
"""

from __future__ import annotations

import importlib.util as _ilu
import os as _os

_stdlib_path = _os.path.join(_os.path.dirname(_os.__file__), "platform.py")
if _os.path.isfile(_stdlib_path):
    _spec = _ilu.spec_from_file_location("__stdlib_platform", _stdlib_path)
    if _spec is not None and _spec.loader is not None:
        _stdlib = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_stdlib)

        # Re-export every public name from the stdlib platform module so that
        # third-party packages which do `import platform; platform.X()` work.
        architecture = _stdlib.architecture
        java_ver = _stdlib.java_ver
        libc_ver = _stdlib.libc_ver
        mac_ver = _stdlib.mac_ver
        machine = _stdlib.machine
        node = _stdlib.node
        platform = _stdlib.platform
        processor = _stdlib.processor
        python_branch = _stdlib.python_branch
        python_build = _stdlib.python_build
        python_compiler = _stdlib.python_compiler
        python_implementation = _stdlib.python_implementation
        python_revision = _stdlib.python_revision
        python_version = _stdlib.python_version
        python_version_tuple = _stdlib.python_version_tuple
        release = _stdlib.release
        system = _stdlib.system
        system_alias = _stdlib.system_alias
        uname = _stdlib.uname
        uname_result = _stdlib.uname_result
        version = _stdlib.version
        win32_edition = _stdlib.win32_edition
        win32_is_iot = _stdlib.win32_is_iot
        win32_ver = _stdlib.win32_ver

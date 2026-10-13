"""Load LeapC without a Python-version-specific compiled binding.

Declarations come from the vendored Ultraleap header (Apache-2.0;
see repo_temp/LICENSE.md). Tracking structs and the connection API used here
also match Orion 4's ABI. See Ultraleap UnityPlugin, commit
ca42f3a59dc8fd6693f1dd15286249a9237b8bdb, LeapCSharp/LeapC.cs.
"""

import os
from pathlib import Path
import platform
import re
import struct


def header_declarations(header):
    """Retain declarations inside the header guard, omitting compiler branches.

    Follows Ultraleap's src/scripts/cffi_build.py header sanitization.
    """
    header = re.sub(r"/\*.*?\*/|//[^\n]*", "", header, flags=re.DOTALL)
    constants = dict(re.findall(r"^#define\s+(LEAP_DISTORTION_MATRIX_N)\s+(\d+)", header, re.MULTILINE))
    result = []
    depth = 0
    for line in header.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            directive = stripped[1:].lstrip()
            if directive.startswith("if"):
                depth += 1
            elif directive.startswith("endif"):
                depth -= 1
            continue
        if depth != 1 or stripped.startswith("LEAP_STATIC_ASSERT"):
            continue
        line = line.replace("LEAP_EXPORT", "").replace("LEAP_CALL", "")
        for name, value in constants.items():
            line = line.replace(name, value)
        result.append(line)
    return "\n".join(result)


def load_leapc(sdk=None):
    from cffi import FFI

    if platform.system() == "Windows" and struct.calcsize("P") != 8:
        raise RuntimeError("Use 64-bit Python with the bundled 64-bit LeapC library.")
    sdk = sdk or os.environ.get("LEAPSDK_INSTALL_LOCATION")
    installed_sdk = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Ultraleap" / "LeapSDK"
    if not sdk and (installed_sdk / "include" / "LeapC.h").is_file():
        sdk = str(installed_sdk)
    if sdk:
        root = Path(sdk).expanduser().resolve()
        header = root / "include" / "LeapC.h"
        library = root / "lib" / "x64" / "LeapC.dll"
        if platform.system() != "Windows":
            library = root / "lib" / ("libLeapC.dylib" if platform.system() == "Darwin" else "libLeapC.so")
    else:
        root = Path(__file__).resolve().parents[1] / "repo_temp" / "leapc-cffi" / "src" / "leapc_cffi"
        header = root / "LeapC.h"
        library = root / "LeapC.dll"
        if platform.system() != "Windows":
            raise RuntimeError("Pass --sdk with a matching LeapC SDK on Linux/macOS. The bundled library is Windows x64.")
        # Orion uses the older service protocol. Its own installed client works
        # with the stable hand/frame ABI above; the bundled Hyperion client
        # cannot connect to an Orion service. Do not upgrade system drivers.
        orion = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Leap Motion" / "Core Services" / "VRVisualizer" / "VRVisualizer_Data" / "Plugins" / "LeapC.dll"
        if orion.is_file():
            library = orion
    if not header.is_file() or not library.is_file():
        raise RuntimeError(f"Missing matching LeapC.h / native library: {header}, {library}")
    ffi = FFI()
    ffi.cdef(header_declarations(header.read_text(encoding="utf-8")), packed=True)
    return ffi, ffi.dlopen(str(library)), library

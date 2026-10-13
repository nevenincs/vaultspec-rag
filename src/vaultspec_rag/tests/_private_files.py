"""Assert a published file is readable by the owning account alone.

Two publications carry a credential: the service discovery records and the
managed qdrant key. Both must land owner-only, and the assertion that proves
it is the same one on each platform, so it lives here once.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def assert_private_file(path: Path) -> None:
    # Mutations granting Everyone access, allowing inheritance, or adding an
    # extra ACE fail the owner/shape assertions; restoring creation passes.
    if sys.platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.stat().st_uid == os.getuid()
        return
    import ctypes
    from ctypes import wintypes

    from .._win32 import _anchor_acl_api, _current_user_sid

    api, kernel32 = _anchor_acl_api()
    api.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.c_void_p,
    )
    api.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = wintypes.BOOL
    api.ConvertStringSidToSidW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    )
    api.ConvertStringSidToSidW.restype = wintypes.BOOL
    descriptor = ctypes.c_void_p()
    text = ctypes.c_wchar_p()
    trustee = ctypes.c_void_p()
    trustee_text = ctypes.c_wchar_p()
    try:
        result = api.GetNamedSecurityInfoW(
            str(path), 1, 4, None, None, None, None, ctypes.byref(descriptor)
        )
        assert result == 0
        assert api.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 4, ctypes.byref(text), None
        )
        owner = _current_user_sid(api, kernel32)
        # Account aliases and auto-inheritance bookkeeping vary by host. The
        # DACL must remain protected, with one uninherited full-access ACE.
        match = re.fullmatch(r"D:P(?:AR)?(?:AI)?\(A;;FA;;;([^()]+)\)", text.value or "")
        assert match is not None, f"not a protected single-owner DACL: {text.value}"
        assert api.ConvertStringSidToSidW(match[1], ctypes.byref(trustee))
        assert api.ConvertSidToStringSidW(trustee, ctypes.byref(trustee_text))
        assert trustee_text.value == owner, "the DACL grants access to another account"
    finally:
        kernel32.LocalFree(trustee_text)
        kernel32.LocalFree(trustee)
        kernel32.LocalFree(text)
        kernel32.LocalFree(descriptor)

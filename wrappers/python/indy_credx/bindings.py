"""Low-level interaction with the indy-credx library."""

import json
import logging
import os
import sys
from ctypes import (
    CDLL,
    byref,
    c_char_p,
    c_int64,
    c_void_p,
)
from ctypes.util import find_library
from typing import Optional, Sequence, Union

from .error import CredxError, CredxErrorCode


CALLBACKS = {}
LIB: CDLL = None
LOGGER = logging.getLogger(__name__)


class ObjectHandle(c_int64):
    """Index of an active IndyObject instance."""

    def __repr__(self) -> str:
        """Format object handle as a string."""
        return f"{self.__class__.__name__}({self.value})"

    def __del__(self):
        object_free(self)


class IndyObject:
    """A generic Indy object allocated by the library."""

    def __init__(self, handle: ObjectHandle) -> "IndyObject":
        self.handle = handle

    def __repr__(self) -> str:
        """Format object as a string."""
        return f"{self.__class__.__name__}({self.handle.value})"

    def to_json(self) -> str:
        return str(object_get_json(self.handle))


class lib_string(c_char_p):
    """A string allocated by the library."""

    @classmethod
    def from_param(cls):
        """Returns the type ctypes should use for loading the result."""
        return c_void_p

    def opt_str(self) -> Optional[str]:
        return self.value.decode("utf-8") if self.value is not None else None

    def __bytes__(self):
        """Convert to bytes."""
        return self.value

    def __str__(self):
        """Convert to str."""
        # not allowed to return None
        return self.value.decode("utf-8") if self.value is not None else ""

    def __del__(self):
        """Call the string destructor when this instance is released."""
        get_library().credx_string_free(self)


def get_library() -> CDLL:
    """Return the CDLL instance, loading it if necessary."""
    global LIB
    if LIB is None:
        LIB = _load_library("indy_credx")
        do_call("credx_set_default_logger")
    return LIB


def library_version() -> str:
    """Get the version of the installed aries-askar library."""
    lib = get_library()
    lib.credx_version.restype = c_void_p
    return str(lib_string(lib.credx_version()))


def _load_library(lib_name: str) -> CDLL:
    """Load the CDLL library.
    The python module directory is searched first, followed by the usual
    library resolution for the current system.
    """
    lib_prefix_mapping = {"win32": ""}
    lib_suffix_mapping = {"darwin": ".dylib", "win32": ".dll"}
    try:
        os_name = sys.platform
        lib_prefix = lib_prefix_mapping.get(os_name, "lib")
        lib_suffix = lib_suffix_mapping.get(os_name, ".so")
        lib_path = os.path.join(
            os.path.dirname(__file__), f"{lib_prefix}{lib_name}{lib_suffix}"
        )
        return CDLL(lib_path)
    except KeyError:
        LOGGER.debug("Unknown platform for shared library")
    except OSError:
        LOGGER.warning("Library not loaded from python package")

    lib_path = find_library(lib_name)
    if not lib_path:
        raise CredxError(CredxErrorCode.WRAPPER, f"Error loading library: {lib_name}")
    try:
        return CDLL(lib_path)
    except OSError as e:
        raise CredxError(
            CredxErrorCode.WRAPPER, f"Error loading library: {lib_name}"
        ) from e


def do_call(fn_name, *args):
    """Perform a synchronous library function call."""
    lib_fn = getattr(get_library(), fn_name)
    result = lib_fn(*args)
    if result:
        raise get_current_error(True)


def get_current_error(expect: bool = False) -> Optional[CredxError]:
    """
    Get the error result from the previous failed API method.

    Args:
        expect: Return a default error message if none is found
    """
    err_json = lib_string()
    if not get_library().credx_get_current_error(byref(err_json)):
        try:
            msg = json.loads(err_json.value)
        except json.JSONDecodeError:
            LOGGER.warning("JSON decode error for credx_get_current_error")
            msg = None
        if msg and "message" in msg and "code" in msg:
            return CredxError(
                CredxErrorCode(msg["code"]), msg["message"], msg.get("extra")
            )
        if not expect:
            return None
    return CredxError(CredxErrorCode.WRAPPER, "Unknown error")


def decode_str(value: c_char_p) -> str:
    return value.decode("utf-8")


def encode_str(arg: Optional[Union[str, bytes, memoryview]]) -> c_char_p:
    """
    Encode an optional input argument as a string.

    Returns: None if the argument is None, otherwise the value encoded utf-8.
    """
    if arg is None:
        return None
    if isinstance(arg, str):
        return c_char_p(arg.encode("utf-8"))
    return c_char_p(arg)


def object_free(handle: ObjectHandle):
    get_library().credx_object_free(handle)


def object_get_json(handle: ObjectHandle) -> lib_string:
    result = lib_string()
    do_call("credx_object_get_json", handle, byref(result))
    return result


def create_schema(
    origin_did: str,
    name: str,
    version: str,
    attr_names: Sequence[str],
    seq_no: int = None,
) -> ObjectHandle:
    result = ObjectHandle()
    do_call(
        "credx_create_schema",
        encode_str(origin_did),
        encode_str(name),
        encode_str(version),
        encode_str(json.dumps(attr_names)),
        c_int64(seq_no or -1),
        byref(result),
    )
    return result
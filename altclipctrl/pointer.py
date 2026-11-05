"""Native cursor coordinates used by calibration and Linux/X11 clicks."""
import ctypes as C
import ctypes.util
import os
import sys
from contextlib import contextmanager


@contextmanager
def x11_pointer():
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        raise RuntimeError('Hue wheel calibration needs Linux/X11.')
    x = C.CDLL(ctypes.util.find_library('X11') or 'libX11.so.6')
    x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
    x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
    x.XCloseDisplay.argtypes = [C.c_void_p]
    x.XFlush.argtypes = [C.c_void_p]
    x.XQueryPointer.argtypes = [C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_ulong),
                               C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_uint)]
    display = x.XOpenDisplay(None)
    if not display:
        raise RuntimeError('Could not connect to the X11 desktop.')
    try:
        root, child = C.c_ulong(), C.c_ulong()
        px, py, wx, wy, mask = C.c_int(), C.c_int(), C.c_int(), C.c_int(), C.c_uint()
        if not x.XQueryPointer(display, x.XDefaultRootWindow(display), C.byref(root), C.byref(child), C.byref(px), C.byref(py), C.byref(wx), C.byref(wy), C.byref(mask)):
            raise RuntimeError('Could not read the X11 pointer position.')
        yield x, display, px.value, py.value, mask.value
    finally:
        x.XCloseDisplay(display)


def cursor_position():
    if sys.platform == 'win32':
        from ctypes import wintypes as W
        point = W.POINT()
        user = C.WinDLL('user32', use_last_error=True)
        user.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
        if not user.GetCursorPos(C.byref(point)):
            raise OSError('Could not read the pointer position.')
        return point.x, point.y
    if sys.platform == 'darwin':
        import Quartz as Q
        point = Q.CGEventGetLocation(Q.CGEventCreate(None))
        return round(point.x), round(point.y)
    with x11_pointer() as (_, _, x, y, _):
        return x, y


def x11_click(x, y):
    with x11_pointer() as (lib, display, old_x, old_y, mask):
        if mask & (1 | 4 | 8 | 64 | 256 | 512 | 1024 | 2048 | 4096):
            return False
        xt = C.CDLL(ctypes.util.find_library('Xtst') or 'libXtst.so.6')
        xt.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
        xt.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
        xt.XTestFakeMotionEvent(display, -1, x, y, 0)
        try:
            xt.XTestFakeButtonEvent(display, 1, 1, 0)
            xt.XTestFakeButtonEvent(display, 1, 0, 0)
        finally:
            xt.XTestFakeMotionEvent(display, -1, old_x, old_y, 0)
            lib.XFlush(display)
        return True

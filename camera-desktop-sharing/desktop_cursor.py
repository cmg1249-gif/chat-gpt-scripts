"""Composite the Windows cursor into desktop frames before resizing/encoding.

DrawIconEx preserves Windows alpha and monochrome AND/XOR cursor rendering.
All GDI objects belong to this call, so simultaneous viewers do not share them.
"""
import ctypes as ct
from ctypes import wintypes as wt
import sys
import numpy as np


class CURSORINFO(ct.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('flags', wt.DWORD),
                ('hCursor', wt.HANDLE), ('ptScreenPos', wt.POINT)]


class ICONINFO(ct.Structure):
    _fields_ = [('fIcon', wt.BOOL), ('xHotspot', wt.DWORD),
                ('yHotspot', wt.DWORD), ('hbmMask', wt.HBITMAP),
                ('hbmColor', wt.HBITMAP)]


class BITMAPINFOHEADER(ct.Structure):
    _fields_ = [('biSize', wt.DWORD), ('biWidth', wt.LONG),
                ('biHeight', wt.LONG), ('biPlanes', wt.WORD),
                ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
                ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', wt.LONG),
                ('biYPelsPerMeter', wt.LONG), ('biClrUsed', wt.DWORD),
                ('biClrImportant', wt.DWORD)]


def _bind(dll, name, args, result):
    function = getattr(dll, name)
    function.argtypes = args
    function.restype = result
    return function


if sys.platform == 'win32':
    _user = ct.WinDLL('user32', use_last_error=True)
    _gdi = ct.WinDLL('gdi32', use_last_error=True)
    _get_cursor = _bind(_user, 'GetCursorInfo', [ct.POINTER(CURSORINFO)], wt.BOOL)
    _copy_icon = _bind(_user, 'CopyIcon', [wt.HANDLE], wt.HANDLE)
    _get_icon = _bind(_user, 'GetIconInfo', [wt.HANDLE, ct.POINTER(ICONINFO)], wt.BOOL)
    _destroy_icon = _bind(_user, 'DestroyIcon', [wt.HANDLE], wt.BOOL)
    _draw = _bind(_user, 'DrawIconEx', [wt.HDC, ct.c_int, ct.c_int, wt.HANDLE,
                 ct.c_int, ct.c_int, wt.UINT, wt.HBRUSH, wt.UINT], wt.BOOL)
    _create_dc = _bind(_gdi, 'CreateCompatibleDC', [wt.HDC], wt.HDC)
    _delete_dc = _bind(_gdi, 'DeleteDC', [wt.HDC], wt.BOOL)
    _create_dib = _bind(_gdi, 'CreateDIBSection', [wt.HDC,
                       ct.POINTER(BITMAPINFOHEADER), wt.UINT,
                       ct.POINTER(ct.c_void_p), wt.HANDLE, wt.DWORD], wt.HBITMAP)
    _select = _bind(_gdi, 'SelectObject', [wt.HDC, wt.HANDLE], wt.HANDLE)
    _delete = _bind(_gdi, 'DeleteObject', [wt.HANDLE], wt.BOOL)
    _flush = _bind(_gdi, 'GdiFlush', [], wt.BOOL)


def draw_cursor(frame, monitor):
    """Return BGR pixels with the visible cursor at its monitor-relative hotspot.

    A hidden/suppressed cursor or unavailable cursor data leaves capture intact.
    MSS sets DPI awareness before this call; its monitor bounds and cursor screen
    coordinates therefore use the same physical-pixel coordinate space.
    """
    if sys.platform != 'win32':
        return frame
    info = CURSORINFO(cbSize=ct.sizeof(CURSORINFO))
    if not _get_cursor(ct.byref(info)) or info.flags != 1 or not info.hCursor:
        return frame
    icon = _copy_icon(info.hCursor)
    if not icon:
        return frame
    details = ICONINFO()
    dc = bitmap = previous = None
    try:
        if not _get_icon(icon, ct.byref(details)):
            return frame
        x = info.ptScreenPos.x - monitor['left'] - details.xHotspot
        y = info.ptScreenPos.y - monitor['top'] - details.yHotspot
        height, width = frame.shape[:2]
        if x >= width or y >= height:
            return frame
        dc = _create_dc(None)
        if not dc:
            return frame
        header = BITMAPINFOHEADER(biSize=ct.sizeof(BITMAPINFOHEADER),
                                  biWidth=width, biHeight=-height,
                                  biPlanes=1, biBitCount=32)
        bits = ct.c_void_p()
        bitmap = _create_dib(dc, ct.byref(header), 0, ct.byref(bits), None, 0)
        if not bitmap or not bits.value:
            return frame
        previous = _select(dc, bitmap)
        if not previous or previous == ct.c_void_p(-1).value:
            previous = None
            return frame
        pixels = np.ctypeslib.as_array(
            (ct.c_ubyte * (width * height * 4)).from_address(bits.value)
        ).reshape(height, width, 4)
        pixels[:, :, :3] = frame
        pixels[:, :, 3] = 255
        if not _draw(dc, x, y, icon, 0, 0, 0, None, 3):
            return frame
        _flush()  # Finish GDI writes before accessing DIB memory directly.
        return pixels[:, :, :3].copy()
    finally:
        if previous:
            _select(dc, previous)
        if bitmap:
            _delete(bitmap)
        if dc:
            _delete_dc(dc)
        for handle in (details.hbmMask, details.hbmColor):
            if handle:
                _delete(handle)
        _destroy_icon(icon)


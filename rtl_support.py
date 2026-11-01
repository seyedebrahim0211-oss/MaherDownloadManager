"""Persian shaping for Tk widgets, with a local fallback if optional packages are absent.

Do not use bidi reversal on text input fields. This helper applies to rendered labels only.
"""
from __future__ import annotations
import unicodedata

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
except ImportError:
    arabic_reshaper = None
    get_display = None

FORMS = {}
for index in list(range(0xFB50,0xFDFF + 1)) + list(range(0xFE70,0xFEFF + 1)):
    glyph = chr(index)
    name = unicodedata.name(glyph, '')
    if not name.endswith('FORM'):
        continue
    base = unicodedata.normalize('NFKC', glyph)
    if len(base) != 1:
        continue
    style = name.split()[-2].lower()
    FORMS.setdefault(base,{})[style] = glyph


def _internal_reshape(value):
    # Simple presentation-form fallback for Arabic + Persian letters. In the
    # released Windows installer the full reshaper / python-bidi is bundled.
    chars = list(value)
    output = []
    def can_join_previous(ch):
        return 'final' in FORMS.get(ch, {}) or 'medial' in FORMS.get(ch,{})
    def can_join_next(ch):
        return 'initial' in FORMS.get(ch,{}) or 'medial' in FORMS.get(ch,{})
    for i, char in enumerate(chars):
        forms = FORMS.get(char)
        if not forms:
            output.append(char)
            continue
        left = i > 0 and can_join_next(chars[i-1]) and can_join_previous(char)
        right = i < len(chars)-1 and can_join_next(char) and can_join_previous(chars[i+1])
        style='medial' if left and right else 'final' if left else 'initial' if right else 'isolated'
        output.append(forms.get(style,forms.get('isolated',char)))
    return ''.join(output)


def _fribidi_reorder(shaped):
    # Optional system fallback: fribidi is available on many Linux desktops.
    # The Windows build uses python-bidi instead.
    import ctypes, ctypes.util
    name = ctypes.util.find_library('fribidi')
    if not name:
        return shaped[::-1]
    lib = ctypes.CDLL(name)
    lib.fribidi_log2vis.argtypes=(ctypes.POINTER(ctypes.c_uint32),ctypes.c_int,
          ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_uint32),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)
    lib.fribidi_log2vis.restype=ctypes.c_int
    n=len(shaped)
    original=(ctypes.c_uint32*n)(*(ord(c) for c in shaped))
    visual=(ctypes.c_uint32*n)()
    base=ctypes.c_uint32(0x0111)  # FRIBIDI_PAR_RTL
    ok=lib.fribidi_log2vis(original,n,ctypes.byref(base),visual,None,None,None)
    return ''.join(chr(v) for v in visual) if ok else shaped[::-1]


def shape(text):
    value=str(text)
    if not any('\u0600'<=ch<='\u06ff' for ch in value):
        return value
    if arabic_reshaper and get_display:
        return get_display(arabic_reshaper.reshape(value),base_dir='R')
    return _fribidi_reorder(_internal_reshape(value))

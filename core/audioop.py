"""
audioop.py - Pure-Python drop-in replacement for the CPython stdlib 'audioop'
extension module, for environments where the compiled audioop.pyd/.so is
missing (e.g. a trimmed/embeddable Python distribution) or was removed
(Python >= 3.13).

Implements exactly the subset of the real audioop API that `pydub` uses
(mul, bias, add, tomono, tostereo, avg, max, rms, reverse, lin2lin, ratecv,
getsample), so `from pydub import AudioSegment` and normal pydub operations
(volume change, overlay/mix, mono<->stereo conversion, resampling, reverse,
WAV export) work without the real C extension.

Not a complete/certified reimplementation of every corner case of the real
audioop module (ulaw/alaw/adpcm codecs are not implemented, width=3 is not
supported) - it only needs to be correct for pydub's own usage.

Drop this file as `audioop.py` directly on the Python import path (e.g. next
to site-packages, or inside Lib/) - since it's named `audioop` (not
`pyaudioop`), it satisfies pydub's *first* import attempt
(`import audioop`) and the `pyaudioop` fallback is never even reached.
"""
from __future__ import annotations

import math
import struct

__all__ = [
    "error", "getsample", "max", "minmax", "avg", "rms", "add", "bias",
    "mul", "tomono", "tostereo", "reverse", "lin2lin", "ratecv",
]

_builtin_max = max
_builtin_min = min


class error(Exception):
    pass


_FMT = {1: ("b", "B"), 2: ("h", "H"), 4: ("i", "I")}


def _check_size(size):
    if size not in (1, 2, 4):
        raise error("Size should be 1, 2 or 4")


def _check_params(length, size):
    _check_size(size)
    if length % size != 0:
        raise error("not a whole number of frames")


def _sample_count(cp, size):
    return len(cp) // size


def _fmt(size, signed=True):
    return _FMT[size][0 if signed else 1]


def _get_sample(cp, size, i, signed=True):
    fmt = "<" + _fmt(size, signed)
    start = i * size
    return struct.unpack_from(fmt, cp, start)[0]


def _get_samples(cp, size, signed=True):
    fmt = "<" + _fmt(size, signed)
    n = _sample_count(cp, size)
    return struct.iter_unpack(fmt, cp[: n * size])


def _put_sample(buf, size, i, val, signed=True):
    fmt = "<" + _fmt(size, signed)
    struct.pack_into(fmt, buf, i * size, val)


def _maxval(size, signed=True):
    if signed:
        return (1 << (size * 8 - 1)) - 1
    return (1 << (size * 8)) - 1


def _minval(size, signed=True):
    if not signed:
        return 0
    return -(1 << (size * 8 - 1))


def _clipfn(size, signed=True):
    lo, hi = _minval(size, signed), _maxval(size, signed)
    return lambda v: _builtin_max(lo, _builtin_min(hi, int(v)))


def _overflow(val, size, signed=True):
    lo, hi = _minval(size, signed), _maxval(size, signed)
    if lo <= val <= hi:
        return int(val)
    bits = size * 8
    if signed:
        offset = 1 << (bits - 1)
        return ((int(val) + offset) % (1 << bits)) - offset
    return int(val) % (1 << bits)


def getsample(cp, size, i):
    _check_params(len(cp), size)
    n = _sample_count(cp, size)
    if not (0 <= i < n):
        raise error("Index out of range")
    return _get_sample(cp, size, i)


def max(cp, size):  # noqa: A001 (matches stdlib audioop API name)
    _check_params(len(cp), size)
    if len(cp) == 0:
        return 0
    return _builtin_max(abs(s[0]) for s in _get_samples(cp, size))


def minmax(cp, size):
    _check_params(len(cp), size)
    mx, mn = 0, 0
    for (s,) in _get_samples(cp, size):
        mx = _builtin_max(mx, s)
        mn = _builtin_min(mn, s)
    return mn, mx


def avg(cp, size):
    _check_params(len(cp), size)
    n = _sample_count(cp, size)
    if n == 0:
        return 0
    total = sum(s[0] for s in _get_samples(cp, size))
    # truncate toward zero like the C implementation
    q, r = divmod(total, n)
    if r and ((r < 0) != (n < 0)):
        q += 1
    return q


def rms(cp, size):
    _check_params(len(cp), size)
    n = _sample_count(cp, size)
    if n == 0:
        return 0
    sum_sq = sum(s[0] * s[0] for s in _get_samples(cp, size))
    return int(math.sqrt(sum_sq / n))


def mul(cp, size, factor):
    _check_params(len(cp), size)
    clip = _clipfn(size)
    n = _sample_count(cp, size)
    result = bytearray(n * size)
    for i, (s,) in enumerate(_get_samples(cp, size)):
        _put_sample(result, size, i, clip(s * factor))
    return bytes(result)


def bias(cp, size, b):
    _check_params(len(cp), size)
    n = _sample_count(cp, size)
    result = bytearray(n * size)
    for i, (s,) in enumerate(_get_samples(cp, size)):
        _put_sample(result, size, i, _overflow(s + b, size))
    return bytes(result)


def add(cp1, cp2, size):
    _check_params(len(cp1), size)
    if len(cp1) != len(cp2):
        raise error("Lengths should be the same")
    clip = _clipfn(size)
    n = _sample_count(cp1, size)
    result = bytearray(n * size)
    s1 = _get_samples(cp1, size)
    s2 = _get_samples(cp2, size)
    for i, ((a,), (b_,)) in enumerate(zip(s1, s2)):
        _put_sample(result, size, i, clip(a + b_))
    return bytes(result)


def tomono(cp, size, fac1, fac2):
    _check_params(len(cp), size)
    clip = _clipfn(size)
    n = _sample_count(cp, size)  # total samples (both channels)
    frames = n // 2
    result = bytearray(frames * size)
    samples = list(s[0] for s in _get_samples(cp, size))
    for i in range(frames):
        left = samples[2 * i]
        right = samples[2 * i + 1]
        val = clip(left * fac1 + right * fac2)
        _put_sample(result, size, i, val)
    return bytes(result)


def tostereo(cp, size, fac1, fac2):
    _check_params(len(cp), size)
    clip = _clipfn(size)
    n = _sample_count(cp, size)
    result = bytearray(n * 2 * size)
    for i, (s,) in enumerate(_get_samples(cp, size)):
        _put_sample(result, size, 2 * i, clip(s * fac1))
        _put_sample(result, size, 2 * i + 1, clip(s * fac2))
    return bytes(result)


def reverse(cp, size):
    _check_params(len(cp), size)
    n = _sample_count(cp, size)
    result = bytearray(n * size)
    for i, (s,) in enumerate(_get_samples(cp, size)):
        _put_sample(result, size, n - i - 1, s)
    return bytes(result)


def lin2lin(cp, size, size2):
    _check_params(len(cp), size)
    _check_size(size2)
    if size == size2:
        return bytes(cp)
    n = _sample_count(cp, size)
    result = bytearray(n * size2)
    shift = 8 * abs(size2 - size)
    for i, (s,) in enumerate(_get_samples(cp, size)):
        if size < size2:
            v = s << shift
        else:
            v = s >> shift
        _put_sample(result, size2, i, _overflow(v, size2))
    return bytes(result)


def ratecv(cp, size, nchannels, inrate, outrate, state, weightA=1, weightB=0):
    """Simple linear-interpolation resampler. Not bit-exact with CPython's
    audioop.ratecv, but produces correct-sounding resampled audio, which is
    all pydub's `set_frame_rate` actually needs."""
    _check_params(len(cp), size)
    if nchannels < 1:
        raise error("# of channels should be >= 1")
    if inrate <= 0 or outrate <= 0:
        raise error("sampling rate not > 0")

    bytes_per_frame = size * nchannels
    if len(cp) % bytes_per_frame != 0:
        raise error("not a whole number of frames")

    frame_count = len(cp) // bytes_per_frame
    signed = True

    # Decode into per-channel sample lists.
    channels = [[0] * frame_count for _ in range(nchannels)]
    for f in range(frame_count):
        base = f * bytes_per_frame
        for c in range(nchannels):
            channels[c][f] = _get_sample(cp, size, (base // size) + c, signed)

    if frame_count == 0 or inrate == outrate:
        return bytes(cp), state

    out_frame_count = _builtin_max(1, round(frame_count * outrate / inrate))
    ratio = frame_count / out_frame_count if out_frame_count else 0

    result = bytearray(out_frame_count * bytes_per_frame)
    for o in range(out_frame_count):
        pos = o * ratio
        i0 = int(pos)
        i1 = _builtin_min(i0 + 1, frame_count - 1)
        frac = pos - i0
        for c in range(nchannels):
            v0 = channels[c][i0]
            v1 = channels[c][i1]
            v = v0 + (v1 - v0) * frac
            idx = o * nchannels + c
            _put_sample(result, size, idx, _overflow(v, size, signed))

    return bytes(result), state


# Not used by pydub - present for API completeness, but unsupported.
def lin2ulaw(cp, size):
    raise NotImplementedError("lin2ulaw is not supported by this pure-Python audioop shim")


def ulaw2lin(cp, size):
    raise NotImplementedError("ulaw2lin is not supported by this pure-Python audioop shim")


def lin2alaw(cp, size):
    raise NotImplementedError("lin2alaw is not supported by this pure-Python audioop shim")


def alaw2lin(cp, size):
    raise NotImplementedError("alaw2lin is not supported by this pure-Python audioop shim")


def lin2adpcm(cp, size, state):
    raise NotImplementedError("lin2adpcm is not supported by this pure-Python audioop shim")


def adpcm2lin(cp, size, state):
    raise NotImplementedError("adpcm2lin is not supported by this pure-Python audioop shim")

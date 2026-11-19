#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Parse raw TCP streams into RTP payloads.

Supports the two common ways a media stream is carried inside a TCP payload:

- RTSP interleaved framing (RFC 2326): '$' | channel(1) | length(2, BE) | RTP
- Bare RTP with 2-byte length prefix (RFC 4571 style): length(2, BE) | RTP

In both cases the RTP header is skipped (including CSRC and optional header
extension) and only the RTP payload is kept, which may be MPEG-TS (RTSP) or
MPEG-PS (RFC 4571 style RTP). RTSP control responses (text) may precede the
interleaved media and are tolerated. Framing is auto-detected per stream by
scoring each candidate framing so both capture kinds work with one code path.
"""

import io
import itertools
import struct

_RTSP_INTERLEAVED = 0x24          # '$'
_RTP_VERSION_MASK = 0xC0
_RTP_VERSION_2 = 0x80


def _unpack_be(data):
    return struct.unpack('>H', data)[0]


def _skip_rtp_header(rtp):
    """Return the payload offset inside an RTP packet (after hdr + CSRC + ext)."""
    if len(rtp) < 12:
        return len(rtp)
    byte0 = rtp[0]
    if (byte0 & _RTP_VERSION_MASK) != _RTP_VERSION_2:
        return len(rtp)
    header_length = 12 + 4 * (byte0 & 0x0F)        # fixed header + CSRCs
    if byte0 & 0x10:                               # extension present
        if len(rtp) < header_length + 4:
            return len(rtp)
        ext_length = _unpack_be(rtp[header_length + 2:header_length + 4])
        header_length += 4 + ext_length * 4
    return header_length


def _find_interleaved_start(data):
    """Offset of the first valid interleaved '$' frame, or None."""
    for pos in range(max(0, len(data) - 3)):
        if data[pos] != _RTSP_INTERLEAVED:
            continue
        length = _unpack_be(data[pos + 2:pos + 4])
        if pos + 4 + length <= len(data):
            return pos
    return None


def _parse_rtsp_interleaved_gen(data):
    """Yield each RTP packet (full frame) from RTSP interleaved framing."""
    start = _find_interleaved_start(data)
    if start is None:
        return
    pos = start
    while pos + 4 <= len(data):
        if data[pos] != _RTSP_INTERLEAVED:
            pos += 1
            continue
        length = _unpack_be(data[pos + 2:pos + 4])
        if pos + 4 + length > len(data):
            break                        # truncated tail
        yield data[pos + 4:pos + 4 + length]
        pos += 4 + length


def _parse_bare_length_gen(data):
    """Yield each RTP packet (full frame) from bare 2-byte-length framing."""
    pos = 0
    while pos + 2 <= len(data):
        length = _unpack_be(data[pos:pos + 2])
        if pos + 2 + length > len(data):
            break
        yield data[pos + 2:pos + 2 + length]
        pos += 2 + length


def _is_interleaved(data):
    """Return True if the data uses RTSP interleaved framing.

    RTSP control responses (text) may precede the interleaved media. The choice
    is made by scoring up to 2000 frames: interleaved yields more valid RTP
    version-2 frames. This avoids false positives when a bare length byte
    happens to equal '$'.
    """
    if not data:
        return False
    inter = list(itertools.islice(_parse_rtsp_interleaved_gen(data), 2000))
    bare = list(itertools.islice(_parse_bare_length_gen(data), 2000))
    def _score(frames):
        return sum(1 for f in frames if len(f) >= 4 and (f[0] & _RTP_VERSION_MASK) == _RTP_VERSION_2)
    return _score(inter) > _score(bare)


def _dump_payload(frames, outfile):
    for rtp in frames:
        outfile.write(rtp[_skip_rtp_header(rtp):])


def extract_payload(tcp_payload: bytes, outfile_name: str):
    """Parse one reassembled TCP stream and write its RTP payloads to a file."""
    with open(outfile_name, 'wb') as outfile:
        if _is_interleaved(tcp_payload):
            _dump_payload(_parse_rtsp_interleaved_gen(tcp_payload), outfile)
        else:
            _dump_payload(_parse_bare_length_gen(tcp_payload), outfile)


def parse_payload(tcp_payload: bytes):
    """Parse one reassembled TCP stream and return the concatenated RTP payloads."""
    out = io.BytesIO()
    if _is_interleaved(tcp_payload):
        _dump_payload(_parse_rtsp_interleaved_gen(tcp_payload), out)
    else:
        _dump_payload(_parse_bare_length_gen(tcp_payload), out)
    return out.getvalue()
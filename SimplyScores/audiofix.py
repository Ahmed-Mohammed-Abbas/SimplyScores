# -*- coding: utf-8 -*-
"""MP4 inspection and the HE-AAC header fix for Enigma2 receivers.

TikTok clips carry HE-AAC audio (AAC-LC + SBR, or + PS for v2: 'mp4a.40.29')
signalled explicitly in the MP4 header. The receivers' GStreamer audio sink
(dvbaudiosink) builds the ADTS headers for the hardware decoder from the
first two bytes of that header and assumes plain AAC-LC, so for HE-AAC it
writes an invalid AAC profile and the decoder stays silent.

The fix rewrites the header (AudioSpecificConfig) to AAC-LC at the core
sample rate, padded to the same length so nothing else in the file moves.
The sink then writes a valid ADTS header and the decoder finds the SBR/PS
data in the stream by itself (implicit signalling, as in DVB broadcasts).
"""
import struct

SAMPLE_RATES = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000, 7350]
MAX_MOOV = 8 * 1024 * 1024
AOT_NAMES = {1: "AAC Main", 2: "AAC-LC", 4: "AAC-LTP", 5: "HE-AAC", 29: "HE-AACv2"}


# --------------------------------------------------------------------------
# Boxes and descriptors
# --------------------------------------------------------------------------
def iter_boxes(data, start, end):
    """(type, box start, payload start, box end) for the boxes in data[start:end]."""
    pos = start
    while pos + 8 <= end:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            return
        yield kind, pos, pos + header, min(pos + size, end)
        pos += size


def _child(data, start, end, kind):
    for k, _, payload, box_end in iter_boxes(data, start, end):
        if k == kind:
            return payload, box_end
    return None


def _descriptor(data, pos, end):
    """(tag, payload start, payload end) of the MPEG-4 descriptor at pos."""
    if pos >= end:
        return None
    tag = data[pos]
    pos += 1
    size = 0
    for _ in range(4):
        if pos >= end:
            return None
        b = data[pos]
        pos += 1
        size = (size << 7) | (b & 0x7F)
        if not b & 0x80:
            break
    return tag, pos, min(pos + size, end)


def _find_dsi(data, pos, end):
    """(offset, length) of the DecoderSpecificInfo inside an esds payload."""
    es = _descriptor(data, pos, end)
    if not es or es[0] != 0x03:
        return None
    p = es[1] + 2                               # ES_ID
    flags = data[p]
    p += 1
    if flags & 0x80:
        p += 2                                  # dependsOn_ES_ID
    if flags & 0x40:
        p += 1 + data[p]                        # URL
    if flags & 0x20:
        p += 2                                  # OCR_ES_Id
    config = _descriptor(data, p, es[2])
    if not config or config[0] != 0x04:
        return None
    info = _descriptor(data, config[1] + 13, config[2])
    if not info or info[0] != 0x05:
        return None
    return info[1], info[2] - info[1]


# --------------------------------------------------------------------------
# AudioSpecificConfig
# --------------------------------------------------------------------------
class _Bits(object):
    def __init__(self, data):
        self.data, self.pos = data, 0

    def read(self, count):
        value = 0
        for _ in range(count):
            index = self.pos >> 3
            byte = self.data[index] if index < len(self.data) else 0
            value = (value << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return value


def parse_asc(asc):
    """AudioSpecificConfig bytes -> dict(aot, core_sfi, rate, out_rate, channels, sbr, ps)."""
    bits = _Bits(asc)

    def object_type():
        value = bits.read(5)
        return 32 + bits.read(6) if value == 31 else value

    def frequency():
        index = bits.read(4)
        if index == 15:
            return index, bits.read(24)
        return index, SAMPLE_RATES[index] if index < len(SAMPLE_RATES) else 0

    aot = object_type()
    sfi, rate = frequency()
    info = {"aot": aot, "core_sfi": sfi, "rate": rate, "out_rate": rate,
            "channels": bits.read(4), "sbr": False, "ps": False}
    if aot in (5, 29):
        info["sbr"], info["ps"] = True, aot == 29
        info["out_rate"] = frequency()[1]
        info["core_aot"] = object_type()
    return info


def lc_header(asc):
    """Same-length AAC-LC header for an explicitly signalled HE-AAC one, else None."""
    if len(asc) < 2:
        return None
    info = parse_asc(asc)
    if info["aot"] not in (5, 29) or info["core_sfi"] >= 13 or info.get("core_aot", 2) != 2:
        return None
    value = (2 << 11) | (info["core_sfi"] << 7) | ((info["channels"] & 0xF) << 3)
    return bytes([value >> 8, value & 0xFF]) + b"\x00" * (len(asc) - 2)


def describe_audio(audio):
    if not audio:
        return "no audio track"
    if audio.get("codec") != "mp4a" or "aot" not in audio:
        return "audio %s" % audio.get("codec", "?")
    name = AOT_NAMES.get(audio["aot"], "AAC type %d" % audio["aot"])
    text = "%s (mp4a.40.%d), %d Hz" % (name, audio["aot"], audio["rate"])
    if audio["sbr"]:
        text += " -> %d Hz" % audio["out_rate"]
    chans = {1: "mono", 2: "stereo"}.get(audio["channels"], "%d ch" % audio["channels"])
    return text + ", " + chans + (" + PS (stereo)" if audio["ps"] else "")


def describe_video(video):
    if not video:
        return "no video track"
    return "%s %dx%d" % (video["codec"], video["width"], video["height"])


# --------------------------------------------------------------------------
# moov
# --------------------------------------------------------------------------
def _parse_trak(data, start, end, base, out):
    mdia = _child(data, start, end, b"mdia")
    if not mdia:
        return
    hdlr = _child(data, mdia[0], mdia[1], b"hdlr")
    handler = bytes(data[hdlr[0] + 8:hdlr[0] + 12]) if hdlr else b""
    minf = _child(data, mdia[0], mdia[1], b"minf")
    stbl = minf and _child(data, minf[0], minf[1], b"stbl")
    stsd = stbl and _child(data, stbl[0], stbl[1], b"stsd")
    if not stsd:
        return
    for kind, _, payload, entry_end in iter_boxes(data, stsd[0] + 8, stsd[1]):
        name = kind.decode("latin-1")
        if handler == b"vide" and out["video"] is None and payload + 28 <= entry_end:
            width, height = struct.unpack(">HH", data[payload + 24:payload + 28])
            out["video"] = {"codec": name, "width": width, "height": height}
        elif handler == b"soun" and out["audio"] is None:
            audio = {"codec": name}
            if kind == b"mp4a" and payload + 28 <= entry_end:
                version = struct.unpack(">H", data[payload + 8:payload + 10])[0]
                children = payload + 28 + {1: 16, 2: 36}.get(version, 0)
                esds = _child(data, children, entry_end, b"esds")
                dsi = esds and _find_dsi(data, esds[0] + 4, esds[1])
                if dsi:
                    offset, length = dsi
                    asc = bytes(data[offset:offset + length])
                    audio.update(parse_asc(asc))
                    audio["dsi"] = (base + offset, asc)
            out["audio"] = audio


def parse_moov(data, base=0):
    """Tracks of a complete 'moov' box; data starts at the box, base is its file offset."""
    out = {"video": None, "audio": None}
    for kind, _, payload, end in iter_boxes(data, 0, len(data)):
        if kind == b"moov":
            for trak, _, trak_payload, trak_end in iter_boxes(data, payload, end):
                if trak == b"trak":
                    _parse_trak(data, trak_payload, trak_end, base, out)
    return out


# --------------------------------------------------------------------------
# Streaming fixer
# --------------------------------------------------------------------------
class StreamFixer(object):
    """Applies the header fix to one link while it streams (start or Range requests)."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.boundaries = {0}      # file offsets known to be top-level box starts
        self.patch = None          # (file offset, new bytes)
        self.media = None          # parse_moov() result once the header was seen

    def _patched(self, data, pos):
        if self.patch is None:
            return data
        offset, new = self.patch
        lo, hi = max(pos, offset), min(pos + len(data), offset + len(new))
        if lo >= hi:
            return data
        data = bytearray(data)
        data[lo - pos:hi - pos] = new[lo - offset:hi - offset]
        return bytes(data)

    def _learn(self, moov, pos):
        try:
            self.media = parse_moov(moov, pos)
        except Exception:               # never break playback over an odd header
            self.media = {"video": None, "audio": None}
            return
        audio = self.media.get("audio") or {}
        if self.enabled and audio.get("dsi"):
            offset, asc = audio["dsi"]
            new = lc_header(asc)
            if new:
                self.patch = (offset, new)

    def wrap(self, chunks, start):
        """Yield chunks of a response that starts at file offset `start`, fixed."""
        if start in self.boundaries:
            return self._walk(iter(chunks), start)
        return self._plain(iter(chunks), start)

    def _plain(self, it, pos):
        for chunk in it:
            if chunk:
                yield self._patched(chunk, pos)
                pos += len(chunk)

    def _walk(self, it, pos):
        buf = b""
        while True:
            while len(buf) < 16:
                chunk = next(it, None)
                if chunk is None:
                    if buf:
                        yield self._patched(buf, pos)
                    return
                buf += chunk
            size, kind = struct.unpack(">I4s", buf[:8])
            header = 8
            if size == 1:
                size, header = struct.unpack(">Q", buf[8:16])[0], 16
            if size == 0 or size < header:            # box runs to the end, or garbage
                yield self._patched(buf, pos)
                for piece in self._plain(it, pos + len(buf)):
                    yield piece
                return
            if kind == b"moov" and size <= MAX_MOOV:
                while len(buf) < size:
                    chunk = next(it, None)
                    if chunk is None:
                        break
                    buf += chunk
                if len(buf) >= size:
                    self._learn(buf[:size], pos)
                moov, buf = buf[:size], buf[size:]
                yield self._patched(moov, pos)
                pos += len(moov)
                self.boundaries.add(pos)
                continue
            self.boundaries.add(pos + size)           # e.g. the moov after a leading mdat
            remaining = size
            while remaining > 0:
                if not buf:
                    buf = next(it, None)
                    if buf is None:
                        return
                piece, buf = buf[:remaining], buf[remaining:]
                yield self._patched(piece, pos)
                pos += len(piece)
                remaining -= len(piece)


def probe(fetch):
    """Media info of a link. fetch(start, end) -> bytes of that range (inclusive end)."""
    head = fetch(0, 262143)
    pos = 0
    while pos + 16 <= len(head):
        size, kind = struct.unpack(">I4s", head[pos:pos + 8])
        header = 8
        if size == 1:
            size, header = struct.unpack(">Q", head[pos + 8:pos + 16])[0], 16
        if size < header:
            break
        if kind == b"moov":
            if size > MAX_MOOV:
                break
            data = head[pos:pos + size]
            if len(data) < size:
                data = fetch(pos, pos + size - 1)
            return parse_moov(data, pos)
        pos += size
        if pos + 16 > len(head) and pos < 1 << 40:      # header beyond what we have
            nxt = fetch(pos, pos + 15)
            if len(nxt) < 16:
                break
            size, kind = struct.unpack(">I4s", nxt[:8])
            if kind == b"moov" and 8 <= size <= MAX_MOOV:
                return parse_moov(fetch(pos, pos + size - 1), pos)
            break
    return None

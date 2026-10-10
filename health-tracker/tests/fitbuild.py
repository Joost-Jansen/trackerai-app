"""A minimal FIT encoder for tests: enough of the format to write an activity the way a bike computer does.

fitdecode only reads, so tests build their own files. Little-endian, one definition per message type, CRCs as in
the FIT SDK.
"""

import struct
from datetime import datetime, timezone

FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
SEMI = 2**31 / 180
_CRC = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401, 0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]
# base types: (code, struct format)
ENUM, UINT8, UINT16, SINT32, UINT32 = (0x00, "B"), (0x02, "B"), (0x84, "H"), (0x85, "i"), (0x86, "I")


def crc(data: bytes, c: int = 0) -> int:
    for b in data:
        tmp = _CRC[c & 0xF]
        c = (c >> 4) & 0x0FFF
        c = c ^ tmp ^ _CRC[b & 0xF]
        tmp = _CRC[c & 0xF]
        c = (c >> 4) & 0x0FFF
        c = c ^ tmp ^ _CRC[(b >> 4) & 0xF]
    return c


def fit_time(dt: datetime) -> int:
    return int((dt - FIT_EPOCH).total_seconds())


class FitWriter:
    def __init__(self):
        self.body = b""
        self.local = {}

    def message(self, global_num: int, fields: list[tuple[int, tuple, int]]):
        """fields: (field number, base type, value)."""
        key = (global_num, tuple((n, t) for n, t, _ in fields))
        if key not in self.local:
            lt = len(self.local)
            self.local[key] = lt
            defs = b"".join(struct.pack("<BBB", n, struct.calcsize(t[1]), t[0]) for n, t, _ in fields)
            self.body += struct.pack("<BBBHB", 0x40 | lt, 0, 0, global_num, len(fields)) + defs
        lt = self.local[key]
        self.body += struct.pack("<B", lt) + b"".join(struct.pack("<" + t[1], v) for _, t, v in fields)

    def bytes(self) -> bytes:
        header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(self.body), b".FIT")
        header += struct.pack("<H", crc(header))
        data = header + self.body
        return data + struct.pack("<H", crc(data))


def bike_ride(start: datetime, seconds: int = 600, manufacturer: int = 32, lat: float = 52.09, lon: float = 5.12,
              hr: int = 140, local_offset_s: int = 7200) -> bytes:
    """A ride of `seconds` seconds, one record every 10 s heading north at 8 m/s. Manufacturer 32 is Wahoo."""
    w = FitWriter()
    t0 = fit_time(start)
    w.message(0, [(0, ENUM, 4), (1, UINT16, manufacturer), (4, UINT32, t0)])
    for i in range(0, seconds + 1, 10):
        w.message(20, [
            (253, UINT32, t0 + i), (0, SINT32, round((lat + i * 8 / 111_000) * SEMI)), (1, SINT32, round(lon * SEMI)),
            (3, UINT8, hr), (5, UINT32, i * 8 * 100), (6, UINT16, 8000), (7, UINT16, 200),
        ])
    end = t0 + seconds
    w.message(18, [
        (253, UINT32, end), (2, UINT32, t0), (5, ENUM, 2), (6, ENUM, 0),
        (7, UINT32, seconds * 1000), (8, UINT32, seconds * 1000), (9, UINT32, seconds * 8 * 100),
        (16, UINT8, hr), (17, UINT8, hr + 20), (22, UINT16, 35),
    ])
    w.message(34, [(253, UINT32, end), (5, UINT32, end + local_offset_s)])
    return w.bytes()

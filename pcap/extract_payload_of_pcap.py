#!/usr/bin/env python3
# -*- coding: UTF-8 -*-


import struct


# --- classic pcap / TCP reassembly helpers (pure python, no scapy needed) ---


def _sniff_endian(path):
    with open(path, 'rb') as f:
        magic = f.read(4)
    if magic == b'\xd4\xc3\xb2\xa1':
        return '<'
    if magic == b'\xa1\xb2\xc3\xd4':
        return '>'
    if magic == b'\x0a\x0d\x0d\x0a':
        raise ValueError('pcapng is not supported, convert to classic pcap first')
    raise ValueError('unsupported capture format: %s' % magic.hex())


def _ip_datagram(frame, linktype):
    """Return the IPv4 datagram from a link-layer frame, or None."""
    if linktype == 1:                       # Ethernet
        if len(frame) < 14 or frame[12:14] != b'\x08\x00':
            return None
        return frame[14:]
    if linktype == 113:                     # Linux cooked capture (SLL)
        if len(frame) < 16 or frame[14:16] != b'\x08\x00':
            return None
        return frame[16:]
    return None


def _reassemble_flows(path):
    """Reassemble TCP payloads per flow.

    Returns a dict: flow_id -> bytes, where flow_id is
    (src_ip, src_port, dst_ip, dst_port). Payloads are ordered by TCP sequence
    number with out-of-order / overlapping segments merged and gaps skipped.
    """
    endian = _sniff_endian(path)
    with open(path, 'rb') as f:
        f.read(4)
        _, _, _, _, _, linktype = struct.unpack(endian + 'HHIIII', f.read(20))

        first_seq = {}     # flow_id -> seq base where stream offset 0 starts
        segments = {}      # flow_id -> {offset: data}
        while True:
            rec = f.read(16)
            if not rec:
                break
            incl_len = struct.unpack(endian + 'IIII', rec)[2]
            frame = f.read(incl_len)
            if len(frame) < incl_len:
                break

            ip = _ip_datagram(frame, linktype)
            if ip is None or len(ip) < 20 or (ip[0] >> 4) != 4:
                continue
            ihl = (ip[0] & 0x0F) * 4
            if ip[9] != 6:                  # TCP only
                continue
            tcp = ip[ihl:]
            if len(tcp) < 20:
                continue

            flow = (ip[12:16], struct.unpack('>H', tcp[0:2])[0],
                    ip[16:20], struct.unpack('>H', tcp[2:4])[0])
            seq = struct.unpack('>I', tcp[4:8])[0]
            data_offset = (tcp[12] >> 4) * 4
            payload = tcp[data_offset:]
            if not payload:
                continue

            base = first_seq.setdefault(flow, seq)
            first_seq[flow] = min(base, seq)
            offset = seq - first_seq[flow]
            if offset < 0:
                continue
            segments.setdefault(flow, {})[offset] = payload

        streams = {}
        for flow, segs in segments.items():
            out = bytearray()
            expect = 0
            for offset in sorted(segs):
                data = segs[offset]
                if offset > expect:
                    expect = offset          # skip gaps
                if offset + len(data) <= expect:
                    continue                 # overlap / retransmission
                start = expect - offset
                out.extend(data[start:])
                expect = offset + len(data)
            streams[flow] = bytes(out)
        return streams


def extract_raw_data(pcap_file):
    """Return a dict of TCP payloads keyed by flow id.

    Each flow is one direction of one TCP connection, reassembled in sequence
    order. Unlike the previous behavior this does NOT concatenate all flows
    together, so independent media streams stay separated.
    """
    return _reassemble_flows(pcap_file)


def extract_sip_data(pcap_file) -> bytes:
    payloads = extract_raw_data(pcap_file)
    filter_bytes = bytearray()
    for flow, data in payloads.items():
        if data.startswith((b'SIP', b'rtsp', b'RTSP', b'OPTIONS', b'DESCRIBE')):
            filter_bytes.extend(data)
    return filter_bytes


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=str, required=True)

    args = parser.parse_args()
    data = extract_raw_data(args.input)
    for flow, payload in data.items():
        print('flow', [f.hex() if isinstance(f, bytes) else f for f in flow],
              'payload', len(payload), 'bytes')
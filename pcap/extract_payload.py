#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import argparse
import os
from pathlib import Path
from .extract_payload_of_pcap import extract_raw_data
from .extract_payload_of_tcpraw import parse_payload


def extract_payload_streams(input_file):
    """Extract media payloads from a pcap.

    Returns a list of (flow, payload_bytes). Each flow is one direction of one
    TCP connection and yields its own MPEG-TS / MPEG-PS payload stream, so
    multi-stream captures produce multiple entries.
    """
    flows = extract_raw_data(input_file)
    streams = []
    for flow, tcp_payload in flows.items():
        payload = parse_payload(tcp_payload)
        if payload:
            streams.append((flow, payload))
    return streams


def extract_payload_from_file(input_file, outfile_name):
    """Extract and write every flow's payload to outfile_name.

    When multiple flows are found, writes each flow to a separate file:
    <stem>.<index>.<ext> (e.g. out_0.data, out_1.data). Returns the list of
    output files written.
    """
    streams = extract_payload_streams(input_file)
    print("tcp payload extract")
    written = []
    if len(streams) <= 1:
        paths = [outfile_name]
    else:
        root, ext = os.path.splitext(outfile_name)
        paths = ['%s.%d%s' % (root, i, ext) for i in range(len(streams))]
    for (flow, payload), path in zip(streams, paths):
        with open(path, 'wb') as f:
            f.write(payload)
        written.append(path)
    return written


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=str, required=True,
                        help="Input .pcap file")
    parser.add_argument('--output', type=str,
                        required=False, help="Output Rtp file")

    args = parser.parse_args()

    input_file = args.input

    output_file = args.output
    stem = Path(input_file).stem
    cwd = os.getcwd()
    if output_file is None:
        output_file = os.path.join(cwd, stem + ".data")
    elif Path(output_file).is_dir():
        output_file = os.path.join(output_file, stem + ".data")
    else:
        pass
    print("Write output to", output_file)

    written = extract_payload_from_file(input_file, output_file)
    print("wrote:", written)

#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import argparse
import os
from pathlib import Path
from .extract_payload_of_pcap import extract_raw_data
from .extract_payload_of_tcpraw import extract_payload


def extract_payload_from_file(input_file, outfile_name):
    tcp_payload = extract_raw_data(input_file)
    print("tcp payload extract")
    extract_payload(outfile_name=outfile_name,
                    tcp_payload=tcp_payload)


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

    extract_payload_from_file(input_file, output_file)

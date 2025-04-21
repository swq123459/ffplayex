#!/usr/bin/env python3
# -*- coding: UTF-8 -*-


from scapy.all import rdpcap, TCP, Raw


def extract_raw_data(pcap_file) -> bytes:
    packets = rdpcap(pcap_file)

    filter_bytes = bytearray()

    for packet in packets:
        if packet.haslayer(TCP) and packet.haslayer(Raw):
            # Extract the raw TCP payload
            raw_data = packet[Raw].load
            filter_bytes.extend(raw_data)

    return filter_bytes


def extract_sip_data(pcap_file) -> bytes:
    packets = rdpcap(pcap_file)

    filter_bytes = bytearray()

    for packet in packets:
        print("Find packet")
        if packet.haslayer("SIP"):
            # Extract the raw TCP payload
            # raw_data = packet["SIP"].load
            print(packet.show())
            # filter_bytes.extend(raw_data)

    return filter_bytes


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=str, required=True)

    args = parser.parse_args()
    input = args.input
    extract_sip_data(pcap_file=input)

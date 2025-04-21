#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import io


def extract_payload(tcp_payload: bytes, outfile_name: str):
    infile = io.BytesIO(tcp_payload)
    with open(outfile_name, 'wb') as outfile:
        while True:
            # Read 2-byte length field
            length_bytes = infile.read(2)
            if not length_bytes:  # End of file
                break
            length = int.from_bytes(length_bytes, 'big')  # Big-endian

            # Read the RTP packet
            rtp_packet = infile.read(length)
            if len(rtp_packet) < length:
                break  # Incomplete packet, end of file

            # Parse RTP header
            byte0 = rtp_packet[0]
            # contains the version (usually 2)
            version = (byte0 >> 6) & 0x03
            if version != 2:
                break

            csrc_count = byte0 & 0x0F  # Last 4 bits
            header_length = 12 + 4 * csrc_count  # Fixed header + CSRCs

            # Check for extension header
            extension = (byte0 >> 4) & 0x01  # Extension bit
            if extension:
                ext_start = 12 + 4 * csrc_count
                ext_len_bytes = rtp_packet[ext_start + 2:ext_start + 4]
                ext_len = int.from_bytes(ext_len_bytes, 'big')
                header_length += 4 + ext_len * 4  # Extension header + data

            payload = rtp_packet[header_length:length]

            # Write payload to output file
            outfile.write(payload)

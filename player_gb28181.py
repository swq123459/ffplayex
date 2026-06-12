#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import socket
import struct
import argparse
import subprocess
import threading
import queue
import http.client

HTTP_LISTEN_HOST = "127.0.0.1"


def _get_free_port(host=HTTP_LISTEN_HOST):
    """Bind to port 0 to let the OS assign a free port, then return it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def parse_rtp_packet(packet):
    """Parse an RTP packet and return (pt, timestamp, payload_bytes).
    Returns (None, None, None) if the packet is malformed.
    """
    if len(packet) < 12:
        return None, None, None

    byte0 = packet[0]
    version = (byte0 >> 6) & 0x03
    has_padding = (byte0 >> 5) & 0x01
    has_extension = (byte0 >> 4) & 0x01
    csrc_count = byte0 & 0x0F

    # Version must be 2 per RFC 3550
    if version != 2:
        return None, None, None

    pt = packet[1] & 0x7F
    timestamp = struct.unpack(">I", packet[4:8])[0]

    # Skip 12-byte mandatory header
    offset = 12

    # Skip CSRC list (csrc_count * 4 bytes)
    offset += csrc_count * 4

    # Skip extension header if present
    if has_extension:
        if offset + 4 > len(packet):
            return None, None, None
        # Extension header: 2-byte profile, 2-byte length (in 32-bit words)
        ext_length = struct.unpack(">H", packet[offset + 2:offset + 4])[0]
        offset += 4 + ext_length * 4

    if offset > len(packet):
        return None, None, None

    # Extract payload
    payload = packet[offset:]

    # Remove padding if present (last byte = number of padding bytes)
    if has_padding and len(payload) > 0:
        padding_len = payload[-1]
        if 0 < padding_len <= len(payload):
            payload = payload[:-padding_len]

    return pt, timestamp, payload


def stream_tcp_to_payload(target, payload_queue, stop_event, buffer_size=65536):
    """Connect to a TCP source, read RFC 4571 framed RTP packets,
    strip headers, and enqueue the raw payload bytes.

    RFC 4571 framing: [2-byte big-endian length][RTP packet]...
    """
    if target.startswith("tcp://"):
        target = target[len("tcp://"):]

    host, sep, port_str = target.rpartition(":")
    if sep == "" or not host or not port_str.isdigit():
        raise ValueError(f"Invalid TCP target: {target}, expected host:port")
    port = int(port_str)

    try:
        with socket.create_connection((host, port), timeout=5) as conn:
            leftover = b""
            while not stop_event.is_set():
                try:
                    conn.settimeout(1.0)  # Allow periodic stop_event check
                    chunk = conn.recv(buffer_size)
                except socket.timeout:
                    continue
                except (ConnectionError, OSError) as e:
                    print(f"TCP connection closed: {e}")
                    break

                if not chunk:
                    print("TCP stream ended (remote closed)")
                    break

                data = leftover + chunk

                # Process framed packets: [2-byte length][RTP packet]...
                while len(data) >= 2 and not stop_event.is_set():
                    packet_length = struct.unpack(">H", data[:2])[0]
                    total_needed = 2 + packet_length

                    if packet_length == 0:
                        # Invalid frame, skip the 2 length bytes
                        data = data[2:]
                        continue

                    if len(data) < total_needed:
                        break  # Need more data from the socket

                    rtp_packet = data[2:total_needed]
                    data = data[total_needed:]

                    # Parse RTP → get PS payload
                    pt, timestamp, payload = parse_rtp_packet(rtp_packet)
                    if payload is not None and len(payload) > 0:
                        payload_queue.put(payload)

                leftover = data

    except Exception as e:
        print(f"TCP stream error: {e}")
    finally:
        # Send sentinel to signal EOF to the HTTP pusher
        payload_queue.put(None)
        print("TCP reader finished")


def push_to_ffplay_http(host, port, payload_queue, stop_event):
    """Connect to ffplay HTTP server and push payload bytes via chunked POST."""
    conn = http.client.HTTPConnection(host, port, timeout=30)
    try:
        conn.connect()
        conn.putrequest("POST", "/")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.endheaders()
        print(f"HTTP push connected to ffplay at {host}:{port}")

        while not stop_event.is_set():
            try:
                payload = payload_queue.get(timeout=1)
            except queue.Empty:
                continue

            if payload is None:
                break

            # Chunked transfer: <hex-size>\r\n<data>\r\n
            chunk_header = f"{len(payload):X}\r\n".encode("ascii")
            conn.send(chunk_header)
            conn.send(payload)
            conn.send(b"\r\n")

        # Terminate chunked body
        conn.send(b"0\r\n\r\n")
        print("HTTP push finished (end of stream)")

    except (ConnectionError, BrokenPipeError, OSError) as e:
        print(f"HTTP push connection error: {e}")
    finally:
        conn.close()


def play(url, etc_list):
    """Main entry point: connect TCP source → strip RTP → push to ffplay HTTP.

    Supports URLs:
      - tcp://host:port          (direct TCP)
      - gb28181pa://host:port/... (passive GB28181, parsed to tcp://host:port)

    Flow:
    1. Start ffplay (HTTP listen mode)
    2. Start TCP reader (queue buffers until ffplay is ready)
    3. push_to_ffplay_http: waits for ffplay, connects, streams
    """

    # Parse gb28181pa:// URL → extract tcp:// target
    if url.startswith("gb28181pa://"):
        url = url[len("gb28181pa://"):]
        # url is now "host:port/path..."
        host_port, _, _ = url.partition("/")
        tcp_target = f"tcp://{host_port}"
        print(f"Parsed gb28181pa URL → {tcp_target}")
    elif url.startswith("tcp://"):
        tcp_target = url
    else:
        raise ValueError(f"Unsupported URL scheme: {url} (expected tcp:// or gb28181pa://)")

    stop_event = threading.Event()
    payload_queue = queue.Queue(maxsize=200)  # Bounded for back-pressure

    etc = " ".join(etc_list)

    # --- Pick a free port ---
    listen_port = _get_free_port()

    # --- Start ffplay in HTTP listen mode ---
    http_url = f"http://{HTTP_LISTEN_HOST}:{listen_port}"
    ffplay_cmd = (
        f"ffplay -hide_banner {etc} "
        f"-window_title {url} "
        f"-listen 1 "
        f"-i {http_url}"
    )
    print("ffplay command:", ffplay_cmd)

    ffplay_proc = subprocess.Popen(
        ffplay_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=True,
    )

    # --- Start TCP reader in background thread ---
    tcp_thread = threading.Thread(
        target=stream_tcp_to_payload,
        args=(tcp_target, payload_queue, stop_event),
        daemon=True,
    )
    tcp_thread.start()

    # --- Push payload to ffplay (waits for ffplay, connects, streams) ---
    try:
        push_to_ffplay_http(
            HTTP_LISTEN_HOST, listen_port, payload_queue, stop_event
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        stop_event.set()
        ffplay_proc.terminate()
        try:
            ffplay_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ffplay_proc.kill()
            ffplay_proc.wait()
        print("GB28181 player stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play a GB28181 TCP RTP stream via ffplay HTTP listen mode."
    )

    parser.add_argument(
        "url",
        type=str,
        help="TCP source URL, e.g. tcp://127.0.0.1:10300",
    )

    parser.add_argument(
        "etc",
        nargs=argparse.REMAINDER,
        help="Additional ffplay options (e.g. -an to disable audio)",
    )

    args = parser.parse_args()

    print("url is", args.url)
    print("etc is", args.etc)

    play(url=args.url, etc_list=args.etc)

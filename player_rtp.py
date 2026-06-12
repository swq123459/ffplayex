#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import socket
import struct
import time
import argparse
import subprocess
import os
import tempfile
import uuid
import threading
import http.client
from urllib.parse import urlparse
import io
import websockets
import ssl
import asyncio

VIDEO_PT = [98, 100]
COM_PT = [96]
AUDIO_PT = [8, 101]  # we'll ignore audio
CLOCK_RATE = 90000
AUDIO_CLOCK = 48000
TCP_LOCAL_PORT = 3888
STREAM_WAIT_INTERVAL = 0.1

VIDEO_UDP = ("127.0.0.1", 1238)


class RtpStreamBuffer:
    def __init__(self):
        self.header = bytearray()
        self.header_ready = False
        self.data = bytearray()
        self.read_offset = 0
        self.closed = False
        self.error = None
        self.condition = threading.Condition()

    def append_header(self, chunk):
        with self.condition:
            if self.header_ready:
                return
            self.header.extend(chunk)
            self.condition.notify_all()

    def set_header(self, chunk):
        with self.condition:
            self.header = bytearray(chunk)
            self.header_ready = True
            self.condition.notify_all()

    def finish_header(self):
        with self.condition:
            self.header_ready = True
            self.condition.notify_all()

    def append_stream(self, chunk):
        with self.condition:
            self.data.extend(chunk)
            self.condition.notify_all()

    def read_exact(self, size, stop_event):
        with self.condition:
            while len(self.data) - self.read_offset < size and not self.closed and not stop_event.is_set():
                self.condition.wait(STREAM_WAIT_INTERVAL)

            available = len(self.data) - self.read_offset
            if available < size:
                return None

            start = self.read_offset
            end = start + size
            chunk = bytes(self.data[start:end])
            self.read_offset = end

            if self.read_offset >= 65536 and self.read_offset >= len(self.data) // 2:
                del self.data[:self.read_offset]
                self.read_offset = 0

            return chunk

    def wait_for_header(self, stop_event):
        with self.condition:
            while not self.header_ready and not self.closed and not stop_event.is_set():
                self.condition.wait(STREAM_WAIT_INTERVAL)
            return bytes(self.header)

    def close(self, error=None):
        with self.condition:
            self.closed = True
            self.error = error
            self.condition.notify_all()


class RtpWrite:
    def __init__(self):
        self.leftover = b''
        self.header_done = False

    def write(self, chunk, header_consumer, stream_consumer, finish_header=None):

        data = self.leftover + chunk
        if not self.header_done:
            # Try to find header separator
            sep_index = data.find(b'\r\n\r\n')
            if sep_index != -1:
                # Write header part including separator
                header_consumer(data[:sep_index])
                # Remaining goes to stream
                if finish_header is not None:
                    finish_header()
                stream_consumer(data[sep_index + len(b'\r\n\r\n'):])
                self.header_done = True
                self.leftover = b''
            else:
                # Header not finished, write all to header
                header_consumer(data)
                self.leftover = b''
        else:
            # After header is done, write directly to stream
            stream_consumer(data)
            self.leftover = b''

def stream_http_to_buffer(url, stream_buffer, buffer_size):
    parsed_url = urlparse(url)

    host = parsed_url.hostname
    port = parsed_url.port or 80
    path = parsed_url.path
    scheme = parsed_url.scheme
    if parsed_url.query:
        path += '?' + parsed_url.query

    # Connect to the server
    if scheme == 'https':
        conn = http.client.HTTPSConnection(host, port)
    else:
        conn = http.client.HTTPConnection(host, port)
    conn.request("GET", path)
    response = conn.getresponse()

    if response.status != 200:
        raise ConnectionError(f"HTTP request failed with status {response.status}")

    writer = RtpWrite()
    try:
        while True:
            chunk = response.read(buffer_size)
            if not chunk:
                break  # Stream ended
            writer.write(
                chunk=chunk,
                header_consumer=stream_buffer.append_header,
                stream_consumer=stream_buffer.append_stream,
                finish_header=stream_buffer.finish_header,
            )
    finally:
        conn.close()
        stream_buffer.close()
    print("Stream processing finished.")


async def stream_ws_to_buffer(url, stream_buffer, buffer_size):
    try:
        if url.startswith("wss://"):
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            ssl_context = None

        async with websockets.connect(url, ssl=ssl_context) as websocket:
            writer = RtpWrite()
            while True:
                data = await websocket.recv()
                if isinstance(data, bytes):  # Ensure binary data
                    writer.write(
                        chunk=data,
                        header_consumer=stream_buffer.append_header,
                        stream_consumer=stream_buffer.append_stream,
                        finish_header=stream_buffer.finish_header,
                    )
                else:
                    print("Received non-binary data, skipping.")

    except Exception as e:
        print(f"Error: {e}")
        stream_buffer.close(error=e)
        return

    stream_buffer.close()


def stream_tcp_to_buffer(target, stream_buffer, buffer_size):
    if target.startswith("tcp://"):
        target = target[len("tcp://"):]

    host, sep, port_str = target.rpartition(":")
    if sep == "" or not host or not port_str.isdigit():
        raise ValueError(f"Invalid TCP target: {target}, expected host:port")
    port = int(port_str)

    default_sdp = "m=video 0 RTP/AVP 96\r\na=rtpmap:96 MP2P/90000"
    stream_buffer.set_header(default_sdp.encode())

    local_bind = ("0.0.0.0", TCP_LOCAL_PORT)
    with socket.create_connection((host, port), source_address=local_bind) as conn:
        while True:
            chunk = conn.recv(buffer_size)
            if not chunk:
                break
            stream_buffer.append_stream(chunk)

    stream_buffer.close()
    print("TCP stream processing finished.")

def stream_to_buffer(url, stream_buffer, buffer_size=1024):
    if url.startswith("http"):
        stream_http_to_buffer(url, stream_buffer, buffer_size)
    elif url.startswith("ws"):
        asyncio.run(stream_ws_to_buffer(url, stream_buffer, buffer_size))
    elif url.startswith("tcp://"):
        stream_tcp_to_buffer(url, stream_buffer, buffer_size)
    else:
        raise ValueError(f"Unsupported stream url: {url}")

def make_temp_name(suffix):
    return os.path.join(tempfile.gettempdir(), str(uuid.uuid1()) + f".{suffix}")

def modify_sdp(input_file, first_port, ip, an):
    with open(input_file, "r") as f:
        lines = f.readlines()

    new_lines = []
    stream_block = []
    in_stream = False
    stream_index = 0  # first media = 0, second media = 1

    for line in lines:
        line_strip = line.strip()
        if not line_strip:
            continue
        if line_strip.startswith("m="):
            # finalize previous stream
            if in_stream:
                stream_block.append(f"c=IN IP4 {ip}\n")
                new_lines.extend(stream_block)
                stream_block = []

            in_stream = True
            # Compute port
            port = first_port + stream_index * 2

            parts = line_strip.split()
            media_type = parts[0].split("=")[1]
            if an is True and media_type == "audio":
                break
            parts[1] = str(port)
            stream_block.append(" ".join(parts) + "\n")
            stream_index += 1
        elif in_stream:
            stream_block.append(line)
        else:
            new_lines.append(line)

    # Handle last stream block
    if in_stream and stream_block:
        stream_block.append(f"c=IN IP4 {ip}\n")
        new_lines.extend(stream_block)
    return new_lines



def start_listen_stream(input, etc, window_title, stop_event):
    command = f'ffplay -hide_banner {etc} -window_title {window_title} -protocol_whitelist file,udp,rtp {input}'
    print("ffmpeg command", command)
    proc = subprocess.Popen(
        command, stdout=subprocess.PIPE, shell=True)
    try:
        while proc.poll() is None:
            if stop_event.is_set():
                proc.terminate()
                break
            time.sleep(0.1)
    finally:
        proc.wait()
        print("Rtp passive player stop success")
        stop_event.set()

def push_stream(stream_buffer, an, socket_url, stop_event):
    prev_video_ts = None
    prev_video_time = None

    prev_audio_ts = None
    prev_audio_time = None

    audio_udp = (socket_url[0], socket_url[1]+2)
    video_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    audio_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        if stop_event.is_set():
            break

        length_bytes = stream_buffer.read_exact(2, stop_event)
        if length_bytes is None:
            if stream_buffer.error is not None:
                raise stream_buffer.error
            print("stream eof")
            break

        packet_length = struct.unpack(">H", length_bytes)[0]
        packet = stream_buffer.read_exact(packet_length, stop_event)
        if packet is None:
            if stream_buffer.error is not None:
                raise stream_buffer.error
            print("Incomplete packet at the end of stream")
            break

        pt = packet[1] & 0x7F
        timestamp = struct.unpack(">I", packet[4:8])[0]

        if pt in VIDEO_PT:
            if prev_video_ts is None:
                prev_video_ts = timestamp
                prev_video_time = time.time()

            rtp_time = (timestamp - prev_video_ts) & 0xFFFFFFFF
            rtp_seconds = rtp_time / CLOCK_RATE
            send_time = prev_video_time + rtp_seconds

            sleep_time = send_time - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)

            video_socket.sendto(packet, socket_url)
            prev_video_ts = timestamp
            prev_video_time = send_time
        elif pt in AUDIO_PT:
            if an is True:
                continue
            if prev_audio_ts is None:
                prev_audio_ts = timestamp
                prev_audio_time = time.time()

            rtp_time = (timestamp - prev_audio_ts) & 0xFFFFFFFF
            rtp_seconds = rtp_time / AUDIO_CLOCK
            send_time = prev_audio_time + rtp_seconds

            sleep_time = send_time - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)

            audio_socket.sendto(packet, audio_udp)
            prev_audio_ts = timestamp
            prev_audio_time = send_time
        elif pt in COM_PT:
            # COM_PT packets are skipped
            pass
        else:
            print(f"Skip rtp packet, pt:{pt}")

            # Send the packet to UDP server
            # udp_socket.sendto(packet, (UDP_IP, UDP_PORT))



def play(url, etc_list):
    stream_buffer = RtpStreamBuffer()
    stop_event = threading.Event()

    def pull_http_stream():
        stream_to_buffer(url=url, stream_buffer=stream_buffer)

    t = threading.Thread(target=pull_http_stream, daemon=True)
    t.start()
    header_bytes = stream_buffer.wait_for_header(stop_event)
    if not header_bytes:
        raise RuntimeError("Failed to receive SDP header from stream")

    sdp_part_file = make_temp_name("sdp")
    with open(sdp_part_file, "wb") as f:
        f.write(header_bytes)

    etc = " ".join(etc_list)
    an = "-an" in etc
    dynamic_sdp_file = make_temp_name("sdp")
    dynamic_sdp_lines = modify_sdp(input_file=sdp_part_file, ip=VIDEO_UDP[0], first_port=VIDEO_UDP[1], an=an)
    dynamic_sdp_content = "".join(dynamic_sdp_lines)
    print(dynamic_sdp_content)

    with open(dynamic_sdp_file, "w") as f:
        f.writelines(dynamic_sdp_lines)

    print(f"dynamic_sdp_file > {dynamic_sdp_file}")

    socket_url = VIDEO_UDP

    def listen_stream():
        start_listen_stream(input=dynamic_sdp_file, etc=etc, window_title=url, stop_event=stop_event)

    pull_thread = threading.Thread(target=listen_stream, daemon=True)
    pull_thread.start()

    time.sleep(3)

    try:
        push_stream(stream_buffer=stream_buffer, an=an, socket_url=socket_url, stop_event=stop_event)
    finally:
        stop_event.set()
        print("Rtp pusher stop success")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play a media URL with additional options.")

    parser.add_argument("url", type=str, help="The URL to play.")

    parser.add_argument("etc", nargs=argparse.REMAINDER,
                        help="Other arguments for play options.")


    args = parser.parse_args()
    url = args.url
    etc_list = args.etc
    print("url is ", url)
    print("etc is ", etc_list)

    play(url=url, etc_list=etc_list)

#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import socket
import struct
import time
import argparse
import subprocess
import time
import os
import tempfile
import uuid
import threading
from pathlib import Path
import http.client
from urllib.parse import urlparse
import io
VIDEO_PT = [98, 100]
COM_PT = [96]
AUDIO_PT = [8, 101]  # we'll ignore audio
CLOCK_RATE = 90000
AUDIO_CLOCK = 48000

VIDEO_UDP = ("127.0.0.1", 1238)



def stream_http_to_files(url, header_file='stream.rtp.sdp', stream_file='stream.rtp', buffer_size=1024):

    parsed_url = urlparse(url)
    if parsed_url.scheme != 'http':
        raise ValueError("Only 'http' scheme is supported")

    host = parsed_url.hostname
    port = parsed_url.port or 80
    path = parsed_url.path
    if parsed_url.query:
        path += '?' + parsed_url.query

    # Connect to the server
    conn = http.client.HTTPConnection(host, port)
    conn.request("GET", path)
    response = conn.getresponse()

    if response.status != 200:
        raise ConnectionError(f"HTTP request failed with status {response.status}")

    header_done = False
    leftover = b''  # leftover bytes from previous read
    with open(header_file, 'wb') as hf, open(stream_file, 'ab') as sf:
        while True:
            chunk = response.read(buffer_size)
            if not chunk:
                break  # Stream ended
            data = leftover + chunk
            if not header_done:
                # Try to find header separator
                sep_index = data.find(b'\r\n\r\n')
                if sep_index != -1:
                    # Write header part including separator
                    hf.write(data[:sep_index])
                    hf.flush()
                    # Remaining goes to stream
                    sf.write(data[sep_index + len(b'\r\n\r\n'):])
                    sf.flush()
                    header_done = True
                else:
                    # Header not finished, write all to header
                    hf.write(data)
                    hf.flush()
                    leftover = b''
            else:
                # After header is done, write directly to stream
                sf.write(data)
                sf.flush()
                leftover = b''

    conn.close()
    print("Stream processing finished.")



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



def start_listen_stream(input, etc, is_mp2p, stop_event):
    if is_mp2p:
        command = f"ffplay -hide_banner -follow 1 -window_title {etc} -i {input}"
    else:
        command = f'ffplay -hide_banner {etc}  -protocol_whitelist file,udp,rtp {input}'
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

def push_stream(input, an, socket_url, is_mp2p, stop_event):
    prev_video_ts = None
    prev_video_time = None

    prev_audio_ts = None
    prev_audio_time = None

    audio_udp = None


    f_mp2p = None
    if is_mp2p:
        socket_url = socket_url[0]
        f_mp2p = open(socket_url, "wb")
    else:
        audio_udp = (socket_url[0], socket_url[1]+2)
        video_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        audio_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Open RTP file in binary mode
    with open(input, "rb") as f:
        while True:
            if stop_event.is_set():
                break
            # Here we assume RTP packets are stored with a 2-byte length prefix
            # Modify if your file format is different
            length_bytes = f.read(2)
            if not length_bytes:
                break  # End of file
            # Unpack packet length (big-endian)
            packet_length = struct.unpack(">H", length_bytes)[0]

            # Read the RTP packet
            packet = f.read(packet_length)
            if len(packet) != packet_length:
                print("Incomplete packet at the end of file")
                break
            pt = packet[1] & 0x7F
            timestamp = struct.unpack(">I", packet[4:8])[0]


            if pt in VIDEO_PT:
                # First packet: initialize
                sleep_time = 0
                if prev_video_ts is None:
                    prev_video_ts = timestamp
                    prev_video_time = time.time()
                else:
                    # If timestamp changed, it's a new frame
                    if timestamp != prev_video_ts:
                        delta_ticks = (timestamp - prev_video_ts) & 0xFFFFFFFF
                        delta_seconds = delta_ticks / CLOCK_RATE

                        # Sleep until next frame
                        now = time.time()
                        sleep_time = prev_video_time + delta_seconds - now

                        if sleep_time > 0:
                            time.sleep(sleep_time)
                            prev_video_ts = timestamp
                            prev_video_time = time.time()

                # payload = packet[12:]  # strip RTP header
                video_socket.sendto(packet, socket_url)
            elif pt in AUDIO_PT:
                if an is True:
                    continue
                if prev_audio_ts is None:
                    prev_audio_ts = timestamp
                    prev_audio_time = time.time()
                elif timestamp != prev_audio_ts:
                    delta_seconds = ((timestamp - prev_audio_ts) & 0xFFFFFFFF) / AUDIO_CLOCK
                    sleep_time = prev_audio_time + delta_seconds - time.time()
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    prev_audio_ts = timestamp
                    prev_audio_time = time.time()
                audio_socket.sendto(packet, audio_udp)
            elif pt in COM_PT:
                payload = packet[12:]
                if f_mp2p is not None:
                    f_mp2p.write(payload)
                # video_socket.sendto(payload, VIDEO_UDP)
            else:
                print(f"Skip rtp packet, pt:{pt}")

            # Send the packet to UDP server
            # udp_socket.sendto(packet, (UDP_IP, UDP_PORT))



def play_rtp_file(url, etc_list):
    input = url
    etc = " ".join(etc_list)
    an = "-an" in etc
    static_sdp_file = f"{input}.sdp"
    if not Path(static_sdp_file).exists():
        raise f"File {static_sdp_file} no exit"
    print(f"Found stati sdp file in {static_sdp_file}")


    dynamic_sdp_file = make_temp_name("sdp")
    mp2p_file = make_temp_name("ps")
    dynamic_sdp_lines = modify_sdp(input_file=static_sdp_file, ip=VIDEO_UDP[0], first_port=VIDEO_UDP[1], an=an)
    dynamic_sdp_content = "".join(dynamic_sdp_lines)
    print(dynamic_sdp_content)

    with open(dynamic_sdp_file, "w") as f:
        f.writelines(dynamic_sdp_lines)
    is_mp2p = "MP2P" in dynamic_sdp_content


    print(f"dynamic_sdp_file > {dynamic_sdp_file}")

    stop_event = threading.Event()

    if is_mp2p is True:
        dynamic_sdp_file = mp2p_file


    def listen_stream():

        start_listen_stream(input=dynamic_sdp_file, etc=etc, is_mp2p=is_mp2p, stop_event=stop_event)

    pull_thread = threading.Thread(target=listen_stream, daemon=True)
    pull_thread.start()


    if is_mp2p:
        socket_url = [mp2p_file]
    else:
        socket_url = VIDEO_UDP

    try:
        push_stream(input=input, an=an, socket_url=socket_url, is_mp2p=is_mp2p, stop_event=stop_event)

    finally:
        stop_event.set()
        print("Rtp pusher stop success")



def play(url, etc_list):
    if url.startswith("http"):
        rtp_part_file = make_temp_name("rtp")
        sdp_part_file = f"{rtp_part_file}.sdp"
        def pull_http_stream():
            stream_http_to_files(url=url, stream_file=rtp_part_file, header_file=sdp_part_file)
        t = threading.Thread(target=pull_http_stream, daemon=True)
        t.start()
        while not os.path.exists(rtp_part_file):
            time.sleep(0.1)
        print("rtp_part_file", rtp_part_file)
        play_rtp_file(url=rtp_part_file, etc_list=etc_list)

    else:
        play_rtp_file(url=url, etc_list=etc_list)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play a media URL with additional options.")

    parser.add_argument("url", type=str, help="The URL to play.")

    parser.add_argument("etc", nargs=argparse.REMAINDER,
                        help="Other arguments for play options.")
    # python .\ffplayex.py  "\\wsl.localhost\Ubuntu\home\swq\mux\build\guojian.rtp" -an
    # python .\ffplayex.py  "\\wsl.localhost\Ubuntu\home\swq\mux\build\duration0mp2p.rtp"

    args = parser.parse_args()
    url = args.url
    etc_list = args.etc
    print("url is ", url)
    print("etc is ", etc_list)

    play(url=url, etc_list=etc_list)

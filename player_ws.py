#!/usr/bin/env python3
# -*- coding: UTF-8 -*-


import argparse
import subprocess
import time
import os
import tempfile
import uuid
import threading
import asyncio
import websockets
import ssl


def make_temp_name():
    return os.path.join(tempfile.gettempdir(), str(uuid.uuid1()) + ".pipe")


async def save_binary_data(uri, output_filename, stop_event):

    try:
        if uri.startswith("wss://"):
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            ssl_context = None
        async with websockets.connect(uri, ssl=ssl_context) as websocket:
            with open(output_filename, 'wb') as file:
                while not stop_event.is_set():
                    data = await websocket.recv()
                    if isinstance(data, bytes):  # Ensure binary data
                        file.write(data)
                    else:
                        print("Received non-binary data, skipping.")

    except Exception as e:
        print(f"Error: {e}")


def play(url, etc):
    etc = " ".join(etc)

    encry_file = make_temp_name()

    print(f"encry > {encry_file}")

    stop_event = threading.Event()

    def pull_stream():
        asyncio.run(save_binary_data(url, encry_file, stop_event))

    pull_thread = threading.Thread(target=pull_stream, daemon=True)
    pull_thread.start()

    # Player
    while not os.path.exists(encry_file):
        time.sleep(0.1)

    subprocess.run(
        f"ffplay -hide_banner -follow 1 -window_title {url}  {etc} -i {encry_file}")

    stop_event.set()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play a media URL with additional options.")

    parser.add_argument("url", type=str, help="The URL to play.")

    parser.add_argument("etc", nargs=argparse.REMAINDER,
                        help="Other arguments for play options.")

    args = parser.parse_args()
    url = args.url
    etc = " ".join(args.etc)
    print("url is ", url)
    print("etc is ", etc)

    play(url=url, etc=etc)


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

from pcap import extract_payload_from_file


def make_temp_name():
    return os.path.join(tempfile.gettempdir(), str(uuid.uuid1()) + ".pipe")


async def save_binary_data(uri, output_filename, stop_event):
    extract_payload_from_file(uri, output_filename)


def play(url, etc):
    etc = " ".join(etc)

    encry_file = make_temp_name()

    print(f"encry > {encry_file}")

    stop_event = threading.Event()

    def pull_stream():
        asyncio.run(save_binary_data(url, encry_file, stop_event))

    pull_thread = threading.Thread(target=pull_stream, daemon=True)
    pull_thread.start()
    pull_thread.join()

    # Player
    while not os.path.exists(encry_file):
        time.sleep(0.1)

    subprocess.run(
        f"ffplay -hide_banner -window_title {url}  {etc} -i {encry_file}")

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

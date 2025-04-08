#!/usr/bin/env python3
# -*- coding: UTF-8 -*-


import argparse
import subprocess
import time
import os
import sys
import tempfile
import signal
import uuid
import requests
import threading
from util import get_exe_path


def make_temp_name():
    return os.path.join(tempfile.gettempdir(), str(uuid.uuid1()) + ".pipe")


def next_value(my_list, value):
    index = my_list.index(value)
    if index + 1 < len(my_list):
        next_element = my_list[index + 1]
        return next_element
    else:
        return None


def paly(url, etc):

    print("url is ", url)

    VKEK_KEY = "--vkek"
    VKEKVERSION_KEY = "--vkekversion"
    if len(etc) < 4:
        sys.exit(f"no {VKEK_KEY} and {VKEKVERSION_KEY} in etc forward")

    if VKEK_KEY not in etc[:4]:
        sys.exit(f"no {VKEK_KEY} in etc forward")
    if VKEKVERSION_KEY not in etc:
        sys.exit(f"no {VKEKVERSION_KEY} in etc forward")

    vkek = next_value(etc, VKEK_KEY)
    vkekversion = next_value(etc, VKEKVERSION_KEY)

    print(f"vkek {vkek}, vkekversion {vkekversion}")

    etc = " ".join(etc[4:])
    print("ffmpeg_etc is ", etc)

    encry_file = make_temp_name()
    decry_file = make_temp_name()

    print(f"encry > {encry_file}")
    print(f"decry > {decry_file}")

    def pull_stream():
        response = requests.get(url, stream=True)
        with open(encry_file, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8000):
                file.write(chunk)
                file.flush()

    def decry_stream():
        exe_path = get_exe_path("decryptor.exe")
        while not os.path.exists(encry_file):
            time.sleep(0.1)
        subprocess.run(
            f"{exe_path} -i {encry_file} -o {decry_file} --vkek {vkek} --vkekversion {vkekversion} --stream true")

    pull_thread = threading.Thread(target=pull_stream, daemon=True)
    pull_thread.start()

    decry_thread = threading.Thread(target=decry_stream, daemon=True)
    decry_thread.start()

    # Player
    while not os.path.exists(decry_file):
        time.sleep(0.1)

    subprocess.run(
        f"ffplay -hide_banner -follow 1 -window_title {url}🔓  {etc} -i {decry_file}")

    decry_thread.join()  # This is very importance to shutdown


def main():
    parser = argparse.ArgumentParser(
        description="Play a media URL with additional options.")
    # print("args: ", sys.argv)
    # url = sys.argv[1]
    parser.add_argument("url", type=str, help="The URL to play.")

    parser.add_argument("etc", nargs=argparse.REMAINDER,
                        help="Other arguments for play options.")

    args = parser.parse_args()
    url = args.url
    etc = args.etc

    paly(url, etc)


if __name__ == "__main__":
    main()

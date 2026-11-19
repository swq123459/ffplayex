#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import argparse
import subprocess
import os
import tempfile
import uuid
import threading

from pcap import extract_payload_streams


def make_temp_name():
    return os.path.join(tempfile.gettempdir(), str(uuid.uuid1()) + ".pipe")


def _ip_str(raw):
    if isinstance(raw, bytes):
        return '.'.join(str(b) for b in raw)
    return str(raw)


def _window_title_for_flow(url, flow):
    src_ip, src_port, dst_ip, dst_port = flow
    return f"{url} {_ip_str(src_ip)}:{src_port}->{_ip_str(dst_ip)}:{dst_port}"


def _play_one(url, payload, flow, etc):
    encry_file = make_temp_name()
    with open(encry_file, 'wb') as f:
        f.write(payload)
    title = _window_title_for_flow(url, flow)
    subprocess.run(
        f"ffplay -hide_banner -window_title \"{title}\" {etc} -i {encry_file}",
        shell=True)
    try:
        os.unlink(encry_file)
    except OSError:
        pass


def play(url, etc):
    etc = " ".join(etc)
    streams = extract_payload_streams(url)
    if not streams:
        print("no media payload found in", url)
        return

    print(f"found {len(streams)} stream(s)")
    windows = []
    for flow, payload in streams:
        t = threading.Thread(
            target=_play_one, args=(url, payload, flow, etc), daemon=True)
        t.start()
        windows.append(t)

    for t in windows:
        t.join()


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
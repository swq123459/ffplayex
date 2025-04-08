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
from util import get_exe_path


def make_temp_name():
    return os.path.join(tempfile.gettempdir(), str(uuid.uuid1()) + ".pipe")


def play(url, etc):
    etc = " ".join(etc)
    exe_path = get_exe_path("GbMediaTool.exe")
    print("exe path is ", exe_path)
    try:

        out = make_temp_name()
        print(f"> {out}")
        evn_params = {"GMT_RECV_TIMEOUT": "1000000000",
                      "GMT_VERBOSE_DISABLE": "1"}
        p = subprocess.Popen(
            f"powershell -noprofile {exe_path} --recv {out} {url}", shell=True, env={**os.environ, **evn_params})

        while p.poll() is None:

            if os.path.exists(out):

                cmd = f'ffplay -follow 1 -window_title {url} {etc} -i {out}'
                print(cmd)
                subprocess.run(cmd)
                break

    finally:

        try:
            while p.poll() is None:
                time.sleep(1)
                p.send_signal(signal.CTRL_C_EVENT)

            p.wait()
        except KeyboardInterrupt as e:
            pass

        if os.path.exists(out):
            os.remove(out)


if __name__ == "__main__":
    print("args: ", sys.argv)
    url = sys.argv[1]
    etc = " ".join(sys.argv[2:])

    play(url=url, etc=etc)

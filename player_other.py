#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import subprocess


def play(url, etc):
    etc = " ".join(etc)

    subprocess.run(
        f"ffplay -hide_banner {etc} -i {url}")

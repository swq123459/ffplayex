#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import argparse
from urllib.parse import urlparse

from player_ws import play as ws_player
from player_other import play as other_player
from player_gb28181 import play as gb28181_player
from player_gb35114 import play as gb35114_player


def main():
    parser = argparse.ArgumentParser(
        description="Play a media URL with additional options.")

    parser.add_argument("url", type=str, help="The URL to play.")

    parser.add_argument("etc", nargs=argparse.REMAINDER,
                        help="Other arguments for play options.")

    args = parser.parse_args()
    url = args.url
    etc = args.etc
    print("url is ", url)
    print("etc is ", etc)
    #
    parsed_url = urlparse(url)
    scheme = parsed_url.scheme

    if scheme == "ws" or scheme == "wss":
        ws_player(url, etc)
    elif scheme.startswith("gb28181"):
        gb28181_player(url, etc)
    elif "--vkek" in etc:
        gb35114_player(url, etc)
    else:
        other_player(url, etc)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
import argparse
from urllib.parse import urlparse
from pathlib import Path
from player_ws import play as ws_player
from player_other import play as other_player
from player_gb28181 import play as gb28181_player
from player_gb35114 import play as gb35114_player
from player_pcap import play as pcap_player
from player_rtp import play as rtp_player
import os
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
    if Path(url).exists():
        suffix = Path(url).suffix.lstrip('.')
        prefix = "file"
    else:
        parsed_url = urlparse(url)
        suffix = os.path.splitext(parsed_url.path)[1].lstrip(".")
        prefix = parsed_url.scheme

    print("prefix is ", prefix)
    print("suffix is ", suffix)

    if ( prefix == "ws" or prefix == "wss" ) and (not suffix == "rtp"):
        ws_player(url, etc)
    elif prefix.startswith("gb28181"):
        gb28181_player(url, etc)
    elif "--vkek" in etc:
        gb35114_player(url, etc)
    elif prefix == "file" and suffix == "pcap":
        pcap_player(url, etc)
    elif suffix == "rtp":
        rtp_player(url, etc)
    else:

        other_player(url, etc)


if __name__ == "__main__":
    main()

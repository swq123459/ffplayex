#!/usr/bin/env python3
# -*- coding: UTF-8 -*-


import argparse
import subprocess
import threading
import queue
import http.client
import socket
import asyncio
import websockets
import ssl

HTTP_LISTEN_HOST = "127.0.0.1"


def _get_free_port(host=HTTP_LISTEN_HOST):
    """Bind to port 0 to let the OS assign a free port, then return it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


async def _stream_ws_to_queue(uri, payload_queue, stop_event):
    """Connect to WebSocket and push received binary data to queue."""
    try:
        if uri.startswith("wss://"):
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            ssl_context = None

        async with websockets.connect(uri, ssl=ssl_context) as websocket:
            while not stop_event.is_set():
                data = await websocket.recv()
                if isinstance(data, bytes):
                    payload_queue.put(data)
                else:
                    print("Received non-binary data, skipping.")
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        payload_queue.put(None)
        print("WebSocket reader finished")


def _run_ws_reader(uri, payload_queue, stop_event):
    """Thread entry: run asyncio loop for WebSocket reader."""
    asyncio.run(_stream_ws_to_queue(uri, payload_queue, stop_event))


def _push_to_ffplay_http(host, port, payload_queue, stop_event):
    """Connect to ffplay HTTP server and push payload bytes via chunked POST."""
    conn = http.client.HTTPConnection(host, port, timeout=30)
    try:
        conn.connect()
        conn.putrequest("POST", "/")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.endheaders()
        print(f"HTTP push connected to ffplay at {host}:{port}")

        while not stop_event.is_set():
            try:
                payload = payload_queue.get(timeout=1)
            except queue.Empty:
                continue

            if payload is None:
                break

            chunk_header = f"{len(payload):X}\r\n".encode("ascii")
            conn.send(chunk_header)
            conn.send(payload)
            conn.send(b"\r\n")

        conn.send(b"0\r\n\r\n")
        print("HTTP push finished (end of stream)")

    except (ConnectionError, BrokenPipeError, OSError) as e:
        print(f"HTTP push connection error: {e}")
    finally:
        conn.close()


def play(url, etc_list):
    """Main entry point: WebSocket source → ffplay HTTP listen mode."""

    stop_event = threading.Event()
    payload_queue = queue.Queue(maxsize=200)

    etc = " ".join(etc_list)

    # --- Pick a free port ---
    listen_port = _get_free_port()

    # --- Start ffplay in HTTP listen mode ---
    http_url = f"http://{HTTP_LISTEN_HOST}:{listen_port}"
    ffplay_cmd = (
        f"ffplay -hide_banner {etc} "
        f"-window_title {url} "
        f"-listen 1 "
        f"-i {http_url}"
    )
    print("ffplay command:", ffplay_cmd)

    ffplay_proc = subprocess.Popen(
        ffplay_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=True,
    )

    # --- Start WebSocket reader in background thread ---
    ws_thread = threading.Thread(
        target=_run_ws_reader,
        args=(url, payload_queue, stop_event),
        daemon=True,
    )
    ws_thread.start()

    # --- Push payload to ffplay ---
    try:
        _push_to_ffplay_http(
            HTTP_LISTEN_HOST, listen_port, payload_queue, stop_event
        )
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        stop_event.set()
        ffplay_proc.terminate()
        try:
            ffplay_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ffplay_proc.kill()
            ffplay_proc.wait()
        print("WebSocket player stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Play a WebSocket media stream via ffplay HTTP listen mode."
    )

    parser.add_argument("url", type=str, help="WebSocket URL, e.g. ws://127.0.0.1:8081/path")

    parser.add_argument(
        "etc",
        nargs=argparse.REMAINDER,
        help="Additional ffplay options (e.g. -an to disable audio)",
    )

    args = parser.parse_args()

    print("url is", args.url)
    print("etc is", args.etc)

    play(url=args.url, etc_list=args.etc)

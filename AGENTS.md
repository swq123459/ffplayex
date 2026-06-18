# ffplay_extension — Agent Guidelines

## Project Overview

A protocol-agnostic streaming dispatcher that extends ffplay to support multiple streaming protocols (RTP over HTTP/WS/TCP, GB28181, GB35114, WebSocket, PCAP replay). It routes URLs to the appropriate player module and feeds media to ffplay via HTTP listen mode.

## Architecture

### Dispatcher Routing (`ffplayex.py`)

The dispatcher selects a player based on **URL scheme + file extension** in this priority order:

| Condition | Player |
|---|---|
| `ws://`/`wss://` (not `.rtp`) | `player_ws.py` |
| `gb28181://` prefix | `player_gb28181.py` |
| `--vkek` in extra args | `player_gb35114.py` |
| `.pcap` file | `player_pcap.py` |
| `.rtp` suffix | `player_rtp.py` |
| Everything else | `player_other.py` |

### Player Pattern

All players follow a **source → buffer → ffplay** pipeline:
1. **Source thread** (daemon): Reads from network/file into a queue or buffer
2. **Consumer thread**: Pushes data to ffplay via chunked HTTP POST (`-listen 1`)
3. **ffplay** is launched with a random free port

Each player module exposes a `play(url, etc_list)` entry point.

## Build & Run

```bash
# Setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run directly
python ffplayex.py <url> [ffplay_options]

# Examples
python ffplayex.py "ws://127.0.0.1:8081/stream" -an
python ffplayex.py "tcp://192.168.1.100:10300" -an
python ffplayex.py "file.pcap"
python ffplayex.py "http://example.com/video.mp4"

# Build executable
pyinstaller .\ffplayex.spec
```

## Conventions

- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants
- **Player entry point**: Each `player_*.py` module exposes `play(url, etc_list)` — `url` is a string, `etc_list` is a list of extra ffplay arguments
- **Stop signal**: Always use `threading.Event` named `stop_event` for cancellable operations
- **Thread safety**: Use `try/finally` to ensure `stop_event.set()` is called
- **Temp files**: UUID-based names via `tempfile.gettempdir()` — clean up when possible
- **New protocols**: Add as `player_<protocol>.py`, register in `ffplayex.py`'s routing chain
- **Constants**: Define protocol-specific constants (PT codes, clock rates, ports) at module top
- **Private helpers**: Prefix with `_snake_case` for module-internal functions

## Dependencies

- **Python packages**: `websockets`, `requests`, `scapy`, `pyinstaller`
- **External binaries** (must be in PATH): `ffplay`
- **Bundled**: `decryptor.exe` (GB35114) — path in `.spec` file

## Common Pitfalls

- **ffplay must be in PATH** — no fallback if missing
- **`shell=True`** used in subprocess calls — be careful with argument validation
- **Hardcoded decryptor path** in `player_gb35114.py` — machine-specific
- **Temp files accumulate** — no cleanup logic currently
- **SSL verification disabled** for WSS connections (`CERT_NONE`)
- **Port binding limited** to `127.0.0.1` — not accessible remotely
- **RTP parsing** assumes RFC 4571 framing (2-byte length prefix) — fails on raw RTP
- **Memory** in `RtpStreamBuffer.data` grows until cleanup triggers at 64KB boundary

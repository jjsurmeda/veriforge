"""A synthetic server-sent-events origin, for proving Caddy does not buffer.

Why this exists instead of running a real chat run: a real run calls a live
model, and this lane has no provider spend. What is under test is Caddy's
`flush_interval -1`, not the api's event generation — and the api's part
(StreamingResponse, `media_type="text/event-stream"`,
`X-Accel-Buffering: no` in `apps/api/runs/router.py`) is already the app's
code, not this lane's.

So this emits a `text/event-stream` response that deliberately does nothing for
`slow` seconds before the first event, then emits `events` events `interval`
seconds apart. Caddy buffering shows up immediately as a wall of silence
followed by everything at once; not buffering shows up as the first event at
~`slow` and the last at ~`slow + events*interval`.

Timing is the assertion, so the timings are reported on stderr and the body is
the events themselves.
"""

from __future__ import annotations

import argparse
import time

FRAME = "id: {seq}\nevent: tick\ndata: {payload}\n\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slow", type=float, default=8.0, help="seconds before the first event")
    parser.add_argument("--events", type=int, default=4)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--path", default="/runs/probe/stream")
    args = parser.parse_args()

    # Served by http.server so this file needs nothing beyond the stdlib; the
    # image has no pip and this is a check fixture, not shipped code.
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 with explicit chunked framing, which is what a real SSE
        # response looks like. Leaving it at HTTP/1.1 with no Content-Length
        # and no Transfer-Encoding delimits the body by connection close, and
        # this handler never closes: the first probe run hung until it was
        # killed at the 800s timeout.
        protocol_version = "HTTP/1.1"

        def _write_chunk(self, payload: bytes) -> None:
            self.wfile.write(b"%x\r\n" % len(payload) + payload + b"\r\n")
            self.wfile.flush()

        def do_GET(self) -> None:  # noqa: N802 - http.server's spelling
            if self.path.rstrip("/") != args.path.rstrip("/"):
                self.send_error(404, "not the probe path")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            start = time.monotonic()
            time.sleep(args.slow)
            for seq in range(args.events):
                elapsed = time.monotonic() - start
                frame = FRAME.format(seq=seq, payload=f'{{"seq":{seq},"at":{elapsed:.2f}}}')
                self._write_chunk(frame.encode())
                print(f"origin sent seq={seq} at t+{elapsed:.2f}s", flush=True)
                if seq < args.events - 1:
                    time.sleep(args.interval)

            # The terminating zero-length chunk, so the client knows the
            # stream ended rather than waiting for the socket to close.
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            elapsed = time.monotonic() - start
            print(f"origin done at t+{elapsed:.2f}s", flush=True)
            self.close_connection = True

        def log_message(self, fmt: str, *a: object) -> None:
            print("origin " + (fmt % a), flush=True)

    server = ThreadingHTTPServer(("0.0.0.0", 8000), Handler)
    print(f"origin listening on 0.0.0.0:8000, path {args.path}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
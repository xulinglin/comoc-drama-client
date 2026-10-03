"""WebView 视频预览服务，支持 byte-range。拆分自 launcher.py。"""
from __future__ import annotations

import mimetypes
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class MediaPreviewServer:
    """Serve registered result videos to WebView with byte-range support."""

    def __init__(self) -> None:
        self._files: dict[str, Path] = {}
        self._lock = threading.Lock()
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def do_HEAD(self) -> None:
                self._serve_media(send_body=False)

            def do_GET(self) -> None:
                self._serve_media(send_body=True)

            def _serve_media(self, send_body: bool) -> None:
                match = re.fullmatch(r"/media/([0-9a-f]{32})", self.path.split("?", 1)[0])
                if not match:
                    self.send_error(404)
                    return
                with registry._lock:
                    media_path = registry._files.get(match.group(1))
                if media_path is None or not media_path.is_file():
                    self.send_error(404)
                    return

                file_size = media_path.stat().st_size
                start, end = 0, max(0, file_size - 1)
                range_header = self.headers.get("Range", "")
                range_match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                partial = range_match is not None
                if range_match:
                    start_text, end_text = range_match.groups()
                    if start_text:
                        start = int(start_text)
                    if end_text:
                        end = min(int(end_text), file_size - 1)
                    if not start_text and end_text:
                        length = min(int(end_text), file_size)
                        start, end = file_size - length, file_size - 1
                    if start >= file_size or start > end:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{file_size}")
                        self.end_headers()
                        return

                content_length = max(0, end - start + 1)
                self.send_response(206 if partial else 200)
                self.send_header("Content-Type", mimetypes.guess_type(media_path.name)[0] or "video/mp4")
                self.send_header("Content-Length", str(content_length))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                if partial:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.end_headers()
                if not send_body:
                    return
                try:
                    with media_path.open("rb") as media:
                        media.seek(start)
                        remaining = content_length
                        while remaining:
                            chunk = media.read(min(1024 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_: Any) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def register(self, path: str | Path) -> str:
        media_path = Path(path).resolve()
        if not media_path.is_file():
            raise FileNotFoundError(media_path)
        token = uuid.uuid4().hex
        with self._lock:
            self._files[token] = media_path
        port = int(self._server.server_address[1])
        return f"http://127.0.0.1:{port}/media/{token}"

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

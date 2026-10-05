"""纯 Python 本地存储服务，替代 comic-drama-storage（Java/JAR）。

数据与文件存储使用标准库（sqlite3 + http.server）；AI 转发使用项目已有的 httpx 和 Pillow：
- /api/storage/health                     健康检查
- /project/**  /chapter/**                项目与章节
- /asset/**                               素材库（含上传）
- /video-project/**                       视频创作任务
- /file/**                                文件桶（上传/下载/信息）
- /api/admin/models/**                    模型管理
- /api/storage/data/**                    通用文档与 OriginalDoubao 账号持久化
- /ai/image                               图片生成与参考图编辑，结果保存到本地文件桶
- /ai/audio /ai/chat /ai/video/**          MiniMax 音色试听、文本转发、Seedance 任务与成片保存
- /prompt/**                              提示词库
- /desktop/account-quota/**               每日额度

兼容接口响应格式：{"code":200,"message":"success","data":...}；通用文档接口返回原始 StoredDocument。
数据保存在 storageDir 下的 storage.db（SQLite）；文件保存在 files/<bucket>/<id>/content.bin。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import mimetypes
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from PIL import Image

SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
DOCUMENT_TABLES = (
    "projects",
    "chapters",
    "assets",
    "video_projects",
    "ai_models",
    "prompts",
    "desktop_account_quota",
    "desktop_account_state",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_segment(value: str, name: str) -> str:
    if not value or not SAFE_SEGMENT.match(value):
        raise StorageError(400, f"{name} 只能包含字母、数字、下划线和短横线")
    return value


class StorageError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class LocalStorage:
    """SQLite 文档存储 + 文件桶，接口对齐 comic-drama-storage。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "storage.db"
        self._lock = threading.RLock()
        self._init_db()

    # ---------- 数据库 ----------

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init_db(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_document (
                    namespace TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    PRIMARY KEY (namespace, object_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS storage_file (
                    bucket TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (bucket, object_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_storage_file_object_id ON storage_file(object_id)"
            )
        self._seed_default_models()

    def _seed_default_models(self) -> None:
        """首次初始化时写入内置模型配置（不含 API Key）。"""
        from model_seeds import DEFAULT_MODELS

        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM storage_document WHERE namespace='ai_models'"
            ).fetchone()
            if int(row["count"]) > 0:
                return
        for model in DEFAULT_MODELS:
            self.create_document("ai_models", dict(model))

    @contextmanager
    def _connection(self):
        with closing(self._connect()) as connection, connection:
            yield connection

    # ---------- 文档 ----------

    def list_documents(self, namespace: str) -> list[dict[str, Any]]:
        _safe_segment(namespace, "namespace")
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                "SELECT object_id, revision, data_json FROM storage_document "
                "WHERE namespace=? ORDER BY updated_at DESC",
                (namespace,),
            ).fetchall()
        return [self._document_payload(row) for row in rows]

    def get_document(self, namespace: str, object_id: str) -> dict[str, Any]:
        _safe_segment(namespace, "namespace")
        _safe_segment(object_id, "id")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT object_id, revision, data_json FROM storage_document "
                "WHERE namespace=? AND object_id=?",
                (namespace, object_id),
            ).fetchone()
        if row is None:
            raise StorageError(404, "数据不存在")
        return self._document_payload(row)

    def create_document(self, namespace: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data or {})
        requested = str(payload.get("id") or "").strip()
        object_id = requested if SAFE_SEGMENT.match(requested) else uuid.uuid4().hex
        now = _now_iso()
        payload["id"] = object_id
        payload.setdefault("createTime", now)
        payload.setdefault("updateTime", now)
        return self.save_document(namespace, object_id, payload, expected_revision=0)

    def update_document(self, namespace: str, object_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get_document(namespace, object_id)
        merged = {key: value for key, value in current.items() if key not in {"revision"}}
        if isinstance(patch, dict):
            merged.update(patch)
        merged["id"] = object_id
        merged["updateTime"] = _now_iso()
        return self.save_document(namespace, object_id, merged, expected_revision=current.get("revision"))

    def delete_document(self, namespace: str, object_id: str, expected_revision: int | None = None) -> None:
        _safe_segment(namespace, "namespace")
        _safe_segment(object_id, "id")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT revision FROM storage_document WHERE namespace=? AND object_id=?", (namespace, object_id)
            ).fetchone()
            current_revision = int(row["revision"]) if row else 0
            if expected_revision is not None and expected_revision != current_revision:
                raise StorageError(409, f"数据版本冲突，当前版本为 {current_revision}")
            connection.execute(
                "DELETE FROM storage_document WHERE namespace=? AND object_id=?",
                (namespace, object_id),
            )

    def save_document(
        self, namespace: str, object_id: str, data: dict[str, Any], expected_revision: int | None
    ) -> dict[str, Any]:
        _safe_segment(namespace, "namespace")
        _safe_segment(object_id, "id")
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        content_hash = _sha256_bytes(payload.encode("utf-8"))
        now = _now_iso()
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT revision FROM storage_document WHERE namespace=? AND object_id=?",
                (namespace, object_id),
            ).fetchone()
            current_revision = int(row["revision"]) if row else 0
            if expected_revision is not None and expected_revision != current_revision:
                raise StorageError(409, f"数据版本冲突，当前版本为 {current_revision}")
            revision = current_revision + 1
            connection.execute(
                """
                INSERT INTO storage_document(namespace, object_id, revision, updated_at, content_hash, data_json)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(namespace, object_id) DO UPDATE SET
                  revision=excluded.revision, updated_at=excluded.updated_at,
                  content_hash=excluded.content_hash, data_json=excluded.data_json
                """,
                (namespace, object_id, revision, now, content_hash, payload),
            )
        result = dict(data)
        result["id"] = object_id
        result["revision"] = revision
        return result

    @staticmethod
    def _document_payload(row: sqlite3.Row) -> dict[str, Any]:
        try:
            data = json.loads(row["data_json"])
        except (TypeError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data["id"] = row["object_id"]
        data["revision"] = int(row["revision"])
        return data

    # ---------- 文件 ----------

    def file_directory(self, bucket: str, object_id: str) -> Path:
        _safe_segment(bucket, "bucket")
        _safe_segment(object_id, "id")
        return self.root / "files" / bucket / object_id

    def save_file(
        self,
        bucket: str,
        content: bytes,
        filename: str,
        content_type: str,
        requested_id: str | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        _safe_segment(bucket, "bucket")
        if not content:
            raise StorageError(400, "文件内容不能为空")
        object_id = requested_id if (requested_id and requested_id.strip()) else "local_" + uuid.uuid4().hex
        _safe_segment(object_id, "id")
        content_hash = _sha256_bytes(content)
        if expected_sha256 and expected_sha256.strip() and content_hash.lower() != expected_sha256.strip().lower():
            raise StorageError(400, "文件哈希校验失败")
        directory = self.file_directory(bucket, object_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "content.bin").write_bytes(content)
        safe_name = self._safe_filename(filename)
        content_type = content_type or "application/octet-stream"
        now = _now_iso()
        meta = {
            "bucket": bucket,
            "id": object_id,
            "name": safe_name,
            "contentType": content_type,
            "size": len(content),
            "sha256": content_hash,
            "updatedAt": now,
        }
        (directory / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT revision FROM storage_file WHERE bucket=? AND object_id=?",
                (bucket, object_id),
            ).fetchone()
            revision = (int(row["revision"]) if row else 0) + 1
            connection.execute(
                """
                INSERT INTO storage_file(bucket, object_id, file_name, content_type, file_size, sha256, revision, updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(bucket, object_id) DO UPDATE SET
                  file_name=excluded.file_name, content_type=excluded.content_type,
                  file_size=excluded.file_size, sha256=excluded.sha256,
                  revision=excluded.revision, updated_at=excluded.updated_at
                """,
                (bucket, object_id, safe_name, content_type, len(content), content_hash, revision, now),
            )
        meta["revision"] = revision
        return meta

    def find_file(self, object_id: str) -> dict[str, Any]:
        _safe_segment(object_id, "id")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT bucket FROM storage_file WHERE object_id=? ORDER BY updated_at DESC LIMIT 1",
                (object_id,),
            ).fetchone()
        if row is None:
            raise StorageError(404, "文件不存在")
        return self.read_file_meta(row["bucket"], object_id)

    def read_file_meta(self, bucket: str, object_id: str) -> dict[str, Any]:
        directory = self.file_directory(bucket, object_id)
        meta_path = directory / "meta.json"
        if not meta_path.is_file():
            raise StorageError(404, "文件不存在")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StorageError(500, "读取文件元数据失败") from exc
        return meta

    def read_file_content(self, bucket: str, object_id: str) -> bytes:
        self.read_file_meta(bucket, object_id)
        content = self.file_directory(bucket, object_id) / "content.bin"
        if not content.is_file():
            raise StorageError(404, "文件内容不存在")
        return content.read_bytes()

    def delete_file(self, bucket: str, object_id: str) -> None:
        directory = self.file_directory(bucket, object_id)
        for name in ("content.bin", "meta.json"):
            try:
                (directory / name).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass
        with self._lock, self._connection() as connection:
            connection.execute(
                "DELETE FROM storage_file WHERE bucket=? AND object_id=?",
                (bucket, object_id),
            )

    @staticmethod
    def _safe_filename(value: str | None) -> str:
        filename = Path(str(value or "file")).name.strip() or "file"
        return re.sub(r"[\r\n]", "_", filename)


class _Handler(BaseHTTPRequestHandler):
    server_version = "LocalStorage/1.0"
    storage: LocalStorage

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - 屏蔽默认日志
        return

    # ---------- 工具 ----------

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data: Any) -> None:
        self._send_json({"code": 200, "message": "success", "data": data})

    def _fail(self, message: str, status: int = 200) -> None:
        self._send_json({"code": 500, "message": message, "data": None}, status)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _read_json(self) -> dict[str, Any]:
        raw = self._read_body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise StorageError(400, "JSON 数据格式不正确") from exc
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], list[tuple[str, str, bytes]]]:
        """解析 multipart/form-data，返回 (普通字段, [(字段名, 文件名, 内容)])。"""
        fields: dict[str, str] = {}
        files: list[tuple[str, str, bytes]] = []
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
        )
        if not message.is_multipart():
            return fields, files
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if not field_name:
                continue
            content = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename is not None:
                files.append((field_name, filename, content))
            else:
                value = content.decode("utf-8", "replace")
                # HTTP clients encode list values as repeated form fields.
                fields[field_name] = fields[field_name] + "\n" + value if field_name in fields else value
        return fields, files

    def _namespace(self, path: str, prefix: str) -> tuple[str, str]:
        rest = path[len(prefix):].strip("/")
        return prefix, unquote(rest)

    # ---------- HTTP 路由 ----------

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            self._route(method, path, query)
        except StorageError as exc:
            self._fail(exc.message, exc.status if exc.status >= 400 else 200)
        except Exception as exc:  # noqa: BLE001 - 兜底，避免线程崩溃
            self._fail(f"存储服务内部错误：{exc}")

    def _route(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        storage = self.storage

        if path == "/api/storage/health":
            self._ok({"status": "ok"})
            return
        if path == "/api/storage/config":
            self._ok({"root": str(storage.root)})
            return

        # Desktop account persistence uses the original raw StoredDocument envelope.
        document_route = re.fullmatch(r"/api/storage/data/([^/]+)(?:/([^/]+))?", path)
        if document_route:
            namespace, object_id = (unquote(value) if value else None for value in document_route.groups())
            def envelope(document):
                return {"namespace": namespace, "id": document["id"], "revision": document["revision"],
                        "updatedAt": document.get("updateTime"),
                        "data": {key: value for key, value in document.items() if key != "revision"}}
            if method == "GET":
                self._send_json(envelope(storage.get_document(namespace, object_id)) if object_id else
                                [envelope(item) for item in storage.list_documents(namespace)])
                return
            if method == "PUT" and object_id:
                body = self._read_json()
                if not isinstance(body.get("data"), dict):
                    raise StorageError(400, "data 必须是 JSON 对象")
                self._send_json(envelope(storage.save_document(namespace, object_id, body["data"],
                                                               body.get("expectedRevision"))))
                return
            if method == "DELETE" and object_id:
                revision = (query.get("expectedRevision") or [None])[0]
                try:
                    revision = int(revision) if revision is not None else None
                except ValueError as exc:
                    raise StorageError(400, "expectedRevision 必须为整数") from exc
                storage.delete_document(namespace, object_id, revision)
                self.send_response(204)
                self.end_headers()
                return

        # 项目
        if path == "/project/list" and method == "GET":
            self._ok(storage.list_documents("projects"))
            return
        if path == "/project" and method == "POST":
            body = self._with_defaults(self._read_json(), {
                "name": "未命名项目", "style": "", "styleDesc": "",
                "ratio": "16:9", "coverId": "", "description": "",
            })
            self._ok(storage.create_document("projects", body))
            return
        chapter_list = re.match(r"^/project/([^/]+)/chapter/list$", path)
        if chapter_list and method == "GET":
            project_id = unquote(chapter_list.group(1))
            items = [item for item in storage.list_documents("chapters")
                     if str(item.get("projectId")) == project_id]
            self._ok(items)
            return
        chapter_create = re.match(r"^/project/([^/]+)/chapter$", path)
        if chapter_create and method == "POST":
            project_id = unquote(chapter_create.group(1))
            storage.get_document("projects", project_id)
            body = self._read_json()
            body["projectId"] = project_id
            self._ok(storage.create_document("chapters", body))
            return
        project_item = re.match(r"^/project/([^/]+)$", path)
        if project_item:
            project_id = unquote(project_item.group(1))
            if method == "GET":
                self._ok(storage.get_document("projects", project_id))
                return
            if method == "PUT":
                self._ok(storage.update_document("projects", project_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("projects", project_id)
                self._ok(None)
                return

        # 章节
        chapter_item = re.match(r"^/chapter/([^/]+)$", path)
        if chapter_item:
            chapter_id = unquote(chapter_item.group(1))
            if method == "PUT":
                self._ok(storage.update_document("chapters", chapter_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("chapters", chapter_id)
                self._ok(None)
                return

        # 素材
        if path == "/asset/list" and method == "GET":
            self._ok(self._filter_assets(storage.list_documents("assets"), query))
            return
        if path == "/asset" and method == "POST":
            body = self._with_defaults(self._read_json(), {
                "type": "image", "name": "", "coverId": "", "description": "",
                "tags": "", "duration": "", "boundProjectIds": [],
            })
            self._ok(storage.create_document("assets", body))
            return
        if path == "/asset/upload" and method == "POST":
            self._ok(self._asset_upload(storage))
            return
        if path == "/asset/upload/batch" and method == "POST":
            self._ok(self._asset_upload(storage, single=False))
            return
        asset_item = re.match(r"^/asset/([^/]+)$", path)
        if asset_item:
            asset_id = unquote(asset_item.group(1))
            if method == "PUT":
                self._ok(storage.update_document("assets", asset_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("assets", asset_id)
                self._ok(None)
                return

        # 视频创作任务
        if path == "/video-project/list" and method == "GET":
            self._ok([self._video_summary(item) for item in storage.list_documents("video_projects")])
            return
        if path == "/video-project" and method == "POST":
            body = self._read_json()
            project_id = str(body.get("projectId") or "").strip()
            if not project_id and "id" not in body:
                raise StorageError(400, "请选择关联项目")
            if project_id:
                storage.get_document("projects", project_id)
            body = self._with_defaults(body, {"name": "未命名任务", "description": "", "assets": [], "storyboards": []})
            self._ok(storage.create_document("video_projects", body))
            return
        video_item = re.match(r"^/video-project/([^/]+)$", path)
        if video_item:
            video_id = unquote(video_item.group(1))
            if method == "GET":
                self._ok(storage.get_document("video_projects", video_id))
                return
            if method == "PUT":
                body = self._read_json()
                if "projectId" in body:
                    storage.get_document("projects", str(body.get("projectId") or ""))
                self._ok(storage.update_document("video_projects", video_id, body))
                return
            if method == "DELETE":
                storage.delete_document("video_projects", video_id)
                self._ok(None)
                return

        # 图片创作会话
        if path == "/image-conversation/list" and method == "GET":
            items = sorted(storage.list_documents("image_conversations"),
                           key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""),
                           reverse=True)
            self._ok(items)
            return
        if path == "/image-conversation" and method == "POST":
            body = self._with_defaults(self._read_json(), {"title": "新对话", "messages": []})
            self._ok(storage.create_document("image_conversations", body))
            return
        conversation_item = re.match(r"^/image-conversation/([^/]+)$", path)
        if conversation_item:
            conversation_id = unquote(conversation_item.group(1))
            if method == "GET":
                self._ok(storage.get_document("image_conversations", conversation_id))
                return
            if method == "PUT":
                self._ok(storage.update_document("image_conversations", conversation_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("image_conversations", conversation_id)
                self._ok(None)
                return

        # 文件
        if path == "/file/upload" and method == "POST":
            self._ok(self._file_upload(storage))
            return
        file_download = re.match(r"^/file/([^/]+)/download$", path)
        if file_download and method in {"GET", "HEAD"}:
            object_id = unquote(file_download.group(1))
            meta = storage.find_file(object_id)
            self._serve_file(storage, meta, method == "GET")
            return
        file_item = re.match(r"^/file/([^/]+)$", path)
        if file_item:
            object_id = unquote(file_item.group(1))
            if method == "GET":
                self._ok(self._legacy_file(storage.find_file(object_id)))
                return
            if method == "DELETE":
                meta = storage.find_file(object_id)
                storage.delete_file(meta["bucket"], object_id)
                self._ok(None)
                return

        # 模型管理
        if path == "/api/admin/models" and method == "GET":
            self._ok(self._sorted_models(storage.list_documents("ai_models")))
            return
        if path == "/api/admin/models" and method == "POST":
            body = self._read_json()
            self._normalize_model(body, partial=False)
            self._ok(storage.create_document("ai_models", body))
            return
        if path == "/api/admin/models/public/list" and method == "GET":
            model_type = (query.get("modelType") or [""])[0]
            items = [item for item in self._sorted_models(storage.list_documents("ai_models"))
                     if item.get("enabled", True)
                     and (not model_type or item.get("modelType") == model_type)]
            for item in items:
                item.pop("apiKey", None)
            self._ok(items)
            return
        model_item = re.match(r"^/api/admin/models/([^/]+)$", path)
        if model_item:
            model_id = unquote(model_item.group(1))
            if method == "PUT":
                patch = self._read_json()
                if not str(patch.get("apiKey") or "").strip():
                    patch.pop("apiKey", None)
                self._normalize_model(patch, partial=True)
                self._ok(storage.update_document("ai_models", model_id, patch))
                return
            if method == "DELETE":
                storage.delete_document("ai_models", model_id)
                self._ok(None)
                return

        # 提示词
        if path == "/prompt/list" and method == "GET":
            items = storage.list_documents("prompts")
            if (query.get("scope") or [""])[0] == "shared":
                items = [item for item in items if item.get("shared")]
            # All local prompts belong to the single-machine user, including shared ones.
            try:
                limit = int((query.get("limit") or ["50"])[0])
            except ValueError as exc:
                raise StorageError(400, "limit 必须为整数") from exc
            self._ok(items[:max(1, min(limit, 500))])
            return
        if path == "/prompt" and method == "POST":
            self._ok(storage.create_document("prompts", self._read_json()))
            return
        prompt_item = re.match(r"^/prompt/([^/]+)$", path)
        if prompt_item:
            prompt_id = unquote(prompt_item.group(1))
            if method == "PUT":
                self._ok(storage.update_document("prompts", prompt_id, self._read_json()))
                return
            if method == "DELETE":
                storage.delete_document("prompts", prompt_id)
                self._ok(None)
                return

        # 每日额度
        if path == "/desktop/account-quota/status" and method == "GET":
            self._ok(self._quota_status(storage, query))
            return
        if path == "/desktop/account-quota/today-usage" and method == "GET":
            self._ok(self._quota_today(storage, query))
            return
        if path == "/desktop/account-quota/consume" and method == "POST":
            self._ok(self._quota_consume(storage))
            return

        if path == "/ai/image" and method == "POST":
            self._ok(self._generate_image(storage, self._read_json()))
            return

        if path == "/ai/audio" and method == "POST":
            self._ok(self._generate_audio(storage, self._read_json()))
            return
        if path == "/ai/chat" and method == "POST":
            self._ok(self._generate_chat(storage, self._read_json()))
            return
        if path == "/ai/video" and method == "POST":
            self._ok(self._submit_video(storage, self._read_json()))
            return
        video_task = re.fullmatch(r"/ai/video/([^/]+)", path)
        if video_task and method == "GET":
            self._ok(self._poll_video(storage, unquote(video_task.group(1)), (query.get("model") or [""])[0]))
            return

        # 未识别的 AI 接口不能误报为用户没有保存配置。
        if path.startswith("/ai/"):
            self._read_body()
            self._fail("当前本地服务尚未接入此 AI 接口")
            return

        raise StorageError(404, "接口不存在")

    # ---------- 辅助 ----------

    def _serve_file(self, storage: LocalStorage, meta: dict[str, Any], send_body: bool) -> None:
        path = storage.file_directory(meta["bucket"], meta["id"]) / "content.bin"
        if not path.is_file():
            raise StorageError(404, "文件内容不存在")
        size = path.stat().st_size
        start, end = 0, size - 1
        range_match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        if range_match:
            first, last = range_match.groups()
            if first:
                start = int(first)
                if last:
                    end = min(int(last), end)
            elif last:
                start = max(0, size - int(last))
            else:
                start = size
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = max(0, end - start + 1)
        self.send_response(206 if range_match else 200)
        self.send_header("Content-Type", meta.get("contentType") or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        if range_match:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if send_body:
            try:
                with path.open("rb") as file:
                    file.seek(start)
                    remaining = length
                    while remaining:
                        chunk = file.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def _resolve_ai_model(self, storage: LocalStorage, model_type: str, selected: Any = "") -> dict[str, Any]:
        selected = str(selected or "").strip()
        models = [item for item in self._sorted_models(storage.list_documents("ai_models"))
                  if item.get("modelType") == model_type and item.get("enabled", True)]
        model = next((item for item in models if str(item.get("id")) == selected), None)
        if model is None:
            model = next((item for item in models if not selected or item.get("modelName") == selected), None)
        label = {"image": "图片", "audio": "音频", "video": "视频", "text": "文本"}[model_type]
        if model is None:
            raise StorageError(400, f"未找到已启用的{label}模型，请在设置中心检查所选模型")
        for key, field in (("apiKey", "API Key"), ("apiUrl", "API 地址"), ("modelName", "API 模型名")):
            if not str(model.get(key) or "").strip():
                raise StorageError(400, f"所选{label}模型未填写 {field}，请在设置中心补充")
        return model

    @staticmethod
    def _ai_endpoint(api_url: str, suffix: str) -> str:
        parsed = urlparse(api_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise StorageError(400, "模型 API 地址必须为有效的 HTTP 或 HTTPS 地址")
        path = parsed.path.rstrip("/")
        if not path.endswith(suffix):
            path = (path or "/v1") + suffix
        return parsed._replace(path=path, fragment="").geturl()

    @staticmethod
    def _request_ai_json(model: dict[str, Any], endpoint: str, operation: str,
                         body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
        api_key = str(model["apiKey"]).strip()
        trust_env = urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}
        try:
            with httpx.Client(timeout=httpx.Timeout(300 if body is not None else 30, connect=15),
                              trust_env=trust_env) as client:
                response = client.request("POST" if body is not None else "GET", endpoint, json=body,
                                          headers={"Authorization": f"Bearer {api_key}", **(headers or {})})
            try:
                result = response.json()
            except ValueError as exc:
                raise StorageError(502, f"{operation}返回非 JSON 内容（HTTP {response.status_code}），请检查 API 地址") from exc
            if not isinstance(result, dict):
                raise StorageError(502, f"{operation}返回格式不正确")
            terminal_task_error = body is None and str(result.get("status") or result.get("state") or "").lower() in {
                "failed", "error", "cancelled", "canceled", "expired"
            }
            if response.is_error or (result.get("error") and not terminal_task_error):
                error = result.get("error") or {}
                detail = error.get("message") if isinstance(error, dict) else str(error)
                detail = str(detail or result.get("message") or "请检查模型配置和服务商状态")
                raise StorageError(502, f"{operation}失败（HTTP {response.status_code}）："
                                   + detail.replace(api_key, "[隐藏]")[:400])
            return result
        except httpx.TimeoutException as exc:
            raise StorageError(504, f"{operation}超时；服务商可能仍在处理，请先检查任务记录再决定是否重试") from exc
        except httpx.HTTPError as exc:
            raise StorageError(502, f"无法连接{operation}服务，请检查网络与 API 地址") from exc

    def _generate_audio(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._resolve_ai_model(storage, "audio", body.get("model"))
        if str(model.get("provider") or "").lower() != "minimax":
            raise StorageError(400, "当前音频生成仅支持 MiniMax 音色设计接口")
        prompt = str(body.get("prompt") or "").strip()
        preview = str(body.get("preview_text") or "").strip()
        if not prompt or not preview:
            raise StorageError(400, "请填写音色描述 prompt 和试听文本 preview_text")
        if len(preview) > 500:
            raise StorageError(400, "试听文本 preview_text 不能超过 500 个字符")
        result = self._request_ai_json(model, self._ai_endpoint(model["apiUrl"], "/voice_design"),
                                       "MiniMax 音频生成", {"prompt": prompt, "preview_text": preview})
        base = result.get("base_resp") or {}
        if not isinstance(base, dict) or base.get("status_code", 0) not in {0, "0"}:
            detail = str(base.get("status_msg") or "未知错误") if isinstance(base, dict) else "返回格式不正确"
            raise StorageError(502, "MiniMax 音频生成失败：" + detail.replace(str(model["apiKey"]), "[隐藏]")[:400])
        try:
            audio = bytes.fromhex(result.get("trial_audio") or "")
        except (ValueError, TypeError) as exc:
            raise StorageError(502, "MiniMax 返回的 trial_audio 不是有效的十六进制音频") from exc
        if not audio:
            raise StorageError(502, "MiniMax 未返回试听音频 trial_audio")
        stored = storage.save_file("generated-audio", audio, f"voice-{uuid.uuid4().hex}.mp3", "audio/mpeg")
        url = self._legacy_file(stored)["url"]
        return {"content": url, "audio_url": url, "fileId": stored["id"], "format": "mp3",
                "voice_id": result.get("voice_id", "")}

    def _generate_chat(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._resolve_ai_model(storage, "text", body.get("model"))
        if not isinstance(body.get("messages"), list) or not body["messages"]:
            raise StorageError(400, "messages 不能为空")
        payload = {**body, "model": model["modelName"], "stream": False}
        headers = {}
        if urlparse(model["apiUrl"]).path.rstrip("/").endswith("/messages"):
            endpoint = self._ai_endpoint(model["apiUrl"], "/messages")
            headers = {"x-api-key": str(model["apiKey"]).strip(), "anthropic-version": "2023-06-01"}
            payload.setdefault("max_tokens", 4096)
        else:
            endpoint = self._ai_endpoint(model["apiUrl"], "/chat/completions")
        return self._request_ai_json(model, endpoint, "文本生成", payload, headers)

    def _video_model(self, storage: LocalStorage, selected: Any) -> dict[str, Any]:
        model = self._resolve_ai_model(storage, "video", selected)
        if str(model.get("provider") or "").lower() != "seedance":
            raise StorageError(400, "当前视频 API 仅支持 Seedance 任务接口")
        return model

    def _submit_video(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        model = self._video_model(storage, body.get("model"))
        if not isinstance(body.get("content"), list) or not body["content"]:
            raise StorageError(400, "视频生成 content 不能为空")
        payload = {key: value for key, value in body.items()
                   if key not in {"remainingPoints", "deductedPoints", "nodeType", "genType", "clientId"}}
        payload["model"] = model["modelName"]
        result = self._request_ai_json(model, self._ai_endpoint(model["apiUrl"], "/tasks"), "Seedance 提交", payload)
        task_id = str(result.get("id") or result.get("task_id") or "").strip()
        if not task_id:
            raise StorageError(502, "Seedance 未返回任务 ID")
        return {**result, "taskId": task_id, "status": result.get("status") or "queued"}

    def _poll_video(self, storage: LocalStorage, task_id: str, selected: str) -> dict[str, Any]:
        model = self._video_model(storage, selected)
        _safe_segment(task_id, "任务 ID")
        cache_id = _sha256_bytes(f"{model['id']}:{task_id}".encode())
        try:
            return storage.get_document("ai_video_results", cache_id)["result"]
        except StorageError as exc:
            if exc.status != 404:
                raise
        parsed = urlparse(self._ai_endpoint(model["apiUrl"], "/tasks"))
        endpoint = parsed._replace(path=parsed.path + "/" + task_id).geturl()
        result = self._request_ai_json(model, endpoint, "Seedance 查询")
        status = str(result.get("status") or result.get("state") or "").lower()
        result["status"] = status
        if status not in {"succeeded", "completed", "done"}:
            return result
        content = result.get("content") if isinstance(result.get("content"), dict) else {}
        video_url = result.get("video_url") or content.get("video_url")
        if not video_url:
            raise StorageError(502, "Seedance 生成完成但没有返回视频地址")
        frame_url = result.get("last_frame_url") or content.get("last_frame_url")
        try:
            trust_env = urlparse(video_url).hostname not in {"127.0.0.1", "localhost", "::1"}
            with httpx.Client(timeout=300, trust_env=trust_env, follow_redirects=True) as client:
                if urlparse(video_url).scheme not in {"http", "https"}:
                    raise StorageError(502, "Seedance 返回的视频地址无效")
                response = client.get(video_url)
                response.raise_for_status()
                mime = response.headers.get("content-type", "video/mp4").split(";")[0].strip()
                if not response.content or (not mime.startswith("video/") and mime != "application/octet-stream"):
                    raise StorageError(502, "Seedance 返回的视频文件为空或内容无效")
                stored = storage.save_file("generated-videos", response.content, f"{task_id}.mp4", mime)
                result["video_url"] = self._legacy_file(stored)["url"]
                result["content"] = {**content, "video_url": result["video_url"]}
                if frame_url:
                    image, mime, extension = self._image_content(frame_url, client)
                    frame = storage.save_file("generated-images", image, f"{task_id}.{extension}", mime)
                    result["last_frame_url"] = self._legacy_file(frame)["url"]
                    result["content"]["last_frame_url"] = result["last_frame_url"]
        except httpx.HTTPError as exc:
            raise StorageError(502, "下载 Seedance 结果失败，请稍后查询此任务，无需重新提交") from exc
        storage.save_document("ai_video_results", cache_id, {"result": result}, expected_revision=None)
        return result

    def _generate_image(self, storage: LocalStorage, body: dict[str, Any]) -> dict[str, Any]:
        models = self._sorted_models(storage.list_documents("ai_models"))
        selected = str(body.get("model") or "").strip()
        models = [item for item in models if item.get("modelType") == "image" and item.get("enabled", True)]
        model = next((item for item in models if str(item.get("id")) == selected), None)
        if model is None:
            model = next((item for item in models if not selected or item.get("modelName") == selected), None)
        if model is None:
            raise StorageError(400, "未找到已启用的图片模型，请在设置中心检查所选模型")
        api_key = str(model.get("apiKey") or "").strip()
        if not api_key:
            raise StorageError(400, "所选图片模型未填写 API Key，请在设置中心补充")
        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            raise StorageError(400, "请填写图片生成描述")
        images = body.get("image") or []
        if not isinstance(images, list):
            images = [images]
        endpoint = self._image_endpoint(str(model.get("apiUrl") or ""), bool(images))
        payload = {key: body[key] for key in (
            "n", "size", "quality", "background", "output_format", "output_compression", "input_fidelity", "user"
        ) if body.get(key) is not None}
        payload.update(model=model["modelName"], prompt=prompt)
        headers = {"Authorization": f"Bearer {api_key}"}
        # Loopback test/provider endpoints must not pass through system proxies.
        trust_env = urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}
        try:
            with httpx.Client(timeout=httpx.Timeout(300, connect=15), trust_env=trust_env) as client:
                if images:
                    files = []
                    for index, source in enumerate(images):
                        content, content_type, extension = self._image_content(source, client)
                        field = "image" if len(images) == 1 else "image[]"
                        files.append((field, (f"reference-{index + 1}.{extension}", content, content_type)))
                    response = client.post(endpoint, headers=headers,
                                           data={key: str(value) for key, value in payload.items()}, files=files)
                else:
                    response = client.post(endpoint, headers=headers, json=payload)
                if response.is_error:
                    try:
                        error = response.json().get("error", {})
                        detail = error.get("message", "") if isinstance(error, dict) else str(error)
                    except (ValueError, AttributeError):
                        detail = ""
                    detail = str(detail).replace(api_key, "[隐藏]")[:400]
                    reason = {401: "API Key 无效", 403: "模型访问被拒绝", 429: "额度不足或请求过于频繁"}.get(
                        response.status_code, "请检查模型名、接口地址及服务商状态")
                    raise StorageError(502, f"图片模型请求失败（HTTP {response.status_code}）：{detail or reason}")
                try:
                    result = response.json()
                except ValueError as exc:
                    raise StorageError(502, "图片模型返回的内容不是 JSON，请检查 API 地址") from exc
                results = result.get("data") if isinstance(result, dict) else None
                if not isinstance(results, list) or not results:
                    raise StorageError(502, "图片模型没有返回图片数据")
                saved = []
                for item in results:
                    if not isinstance(item, dict):
                        raise StorageError(502, "图片模型返回的图片数据格式不正确")
                    source = (f"data:image/png;base64,{item['b64_json']}" if item.get("b64_json") else item.get("url"))
                    if not source:
                        raise StorageError(502, "图片模型没有返回图片地址或 Base64 数据")
                    content, content_type, extension = self._image_content(source, client)
                    stored = storage.save_file("files", content, f"generated-{uuid.uuid4().hex}.{extension}", content_type)
                    saved.append(self._legacy_file(stored))
                first = saved[0]
                return {"content": first["url"], "url": first["url"], "fileId": first["id"], "data": saved}
        except httpx.TimeoutException as exc:
            raise StorageError(504, "图片请求超时；服务商可能仍在处理，请先检查其任务记录再决定是否重试") from exc
        except httpx.HTTPError as exc:
            raise StorageError(502, "无法请求图片服务或下载结果，请检查网络与 API 地址") from exc

    @staticmethod
    def _image_endpoint(api_url: str, editing: bool) -> str:
        parsed = urlparse(api_url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise StorageError(400, "图片模型 API 地址必须为有效的 HTTP 或 HTTPS 地址")
        action = "edits" if editing else "generations"
        api_path = parsed.path.rstrip("/")
        if re.search(r"/images/(generations|edits)$", api_path):
            api_path = api_path.rsplit("/", 1)[0] + "/" + action
        else:
            api_path = (api_path or "/v1") + "/images/" + action
        return parsed._replace(path=api_path, fragment="").geturl()

    @staticmethod
    def _image_content(source: Any, client: httpx.Client) -> tuple[bytes, str, str]:
        if not isinstance(source, str):
            raise StorageError(400, "图片数据必须为 Base64 图片或 HTTP 图片地址")
        if source.startswith("data:"):
            header, separator, encoded = source.partition(",")
            if not separator or not header.startswith("data:image/") or not header.endswith(";base64"):
                raise StorageError(400, "参考图片的 Base64 格式不正确")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise StorageError(400, "图片 Base64 数据无法解析") from exc
        elif urlparse(source).scheme in {"http", "https"}:
            response = client.get(source, follow_redirects=True, timeout=60)
            response.raise_for_status()
            content = response.content
        else:
            raise StorageError(400, "图片地址必须使用 HTTP 或 HTTPS")
        try:
            with Image.open(io.BytesIO(content)) as image:
                image_format = image.format
                image.verify()
            content_type, extension = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"),
                                       "WEBP": ("image/webp", "webp")}[image_format]
        except (OSError, ValueError, KeyError, Image.DecompressionBombError) as exc:
            raise StorageError(400, "图片内容无效或不是支持的 PNG、JPEG、WebP 格式") from exc
        return content, content_type, extension

    @staticmethod
    def _with_defaults(body: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
        for key, value in defaults.items():
            body.setdefault(key, value)
        return body

    @staticmethod
    def _filter_assets(items: list[dict[str, Any]], query: dict[str, list[str]]) -> list[dict[str, Any]]:
        asset_type = (query.get("type") or [""])[0]
        keyword = (query.get("keyword") or [""])[0].strip().lower()
        result = []
        for item in items:
            if asset_type and asset_type not in ("all", item.get("type")):
                continue
            if keyword:
                haystack = f"{item.get('name', '')} {item.get('description', '')} {item.get('tags', '')}".lower()
                if keyword not in haystack:
                    continue
            result.append(item)
        return result

    def _asset_upload(self, storage: LocalStorage, single: bool = True) -> dict[str, Any] | list[dict[str, Any]]:
        fields, files = self._parse_multipart(self._read_body(), self.headers.get("Content-Type") or "")
        if not files:
            raise StorageError(400, "请选择要上传的文件")
        bindings = list(dict.fromkeys(item.strip() for item in fields.get("boundProjectIds", "").splitlines()
                                      if item.strip()))
        assets = []
        for _, filename, content in files[:1] if single else files:
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            stored = storage.save_file("assets", content, filename, content_type)
            media_type = "audio" if content_type.startswith("audio/") else ("video" if content_type.startswith("video/") else "image")
            body = {
                "name": fields.get("name", "").strip() or Path(filename).stem,
                "description": fields.get("description", ""), "tags": fields.get("tags", ""),
                "type": fields.get("type", "").strip() or ("scene" if media_type == "video" else media_type),
                "duration": fields.get("duration", ""), "coverId": stored["id"], "boundProjectIds": bindings,
            }
            asset = storage.create_document("assets", body)
            asset["mediaType"] = media_type
            assets.append(asset)
        return assets[0] if single else assets

    def _file_upload(self, storage: LocalStorage) -> dict[str, Any]:
        fields, files = self._parse_multipart(self._read_body(), self.headers.get("Content-Type") or "")
        if not files:
            raise StorageError(400, "请选择要上传的文件")
        _, filename, content = files[0]
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        stored = storage.save_file(fields.get("bucket", "").strip() or "files", content, filename, content_type)
        return self._legacy_file(stored)

    @staticmethod
    def _legacy_file(stored: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": stored.get("id"),
            "fileName": stored.get("name"),
            "cosKey": stored.get("sha256"),
            "bucket": stored.get("bucket"),
            "fileSize": stored.get("size"),
            "contentType": stored.get("contentType"),
            "url": f"/file/{stored.get('id')}/download",
            "deleted": False,
            "createTime": stored.get("updatedAt"),
            "updateTime": stored.get("updatedAt"),
        }

    @staticmethod
    def _video_summary(source: dict[str, Any]) -> dict[str, Any]:
        result = dict(source)
        assets = source.get("assets") if isinstance(source.get("assets"), list) else []
        storyboards = source.get("storyboards") if isinstance(source.get("storyboards"), list) else []
        active_statuses = {"preparing", "submitting", "queued", "pending", "generating", "processing", "running"}
        completed = 0
        running = 0
        for shot in storyboards:
            if not isinstance(shot, dict):
                continue
            has_result = bool(str(shot.get("resultFileId") or "").strip()
                              or str(shot.get("resultUrl") or "").strip())
            if has_result:
                completed += 1
                continue
            status = str(shot.get("status") or "").strip().lower()
            task_id = str(shot.get("taskId") or shot.get("seedanceTaskId") or "").strip()
            if status in active_statuses or (task_id and status not in {"succeeded", "failed", "cancelled", "canceled"}):
                running += 1
        for asset in assets:
            if isinstance(asset, dict) and str(asset.get("generatingStartedAt") or "").strip():
                running += 1
        result["assetCount"] = len(assets)
        result["storyboardCount"] = len(storyboards)
        result["completedCount"] = completed
        result["runningCount"] = running
        result.pop("assets", None)
        result.pop("storyboards", None)
        return result

    @staticmethod
    def _sorted_models(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda item: int(item.get("sortOrder") or 0))

    @staticmethod
    def _normalize_model(body: dict[str, Any], partial: bool) -> None:
        model_types = {"text", "image", "video", "audio"}
        if not partial or "name" in body:
            name = str(body.get("name") or "").strip()
            if not name:
                raise StorageError(400, "请输入模型显示名称")
            body["name"] = name
        if not partial or "modelType" in body:
            if str(body.get("modelType") or "") not in model_types:
                raise StorageError(400, "模型类型不正确")
        if not partial or "modelName" in body:
            if not str(body.get("modelName") or "").strip():
                raise StorageError(400, "请输入 API 模型名")
        if not partial or "apiUrl" in body:
            api_url = str(body.get("apiUrl") or "").strip()
            if not api_url:
                raise StorageError(400, "请输入 API 地址")
            body["apiUrl"] = re.sub(r"/+$", "", api_url)
        if not partial:
            body.setdefault("provider", "")
            body.setdefault("icon", "")
            body.setdefault("sortOrder", 0)
            body.setdefault("points", 0)
            body.setdefault("enabled", True)

    def _quota_status(self, storage: LocalStorage, query: dict[str, list[str]]) -> dict[str, Any]:
        account_id = (query.get("accountId") or [""])[0]
        record = self._quota_record(storage, account_id)
        return {"accountId": account_id, "date": self._today(), "generatedCount": record.get("generatedCount", 0),
                "dailyLimit": record.get("dailyLimit", 3), "exhausted": record.get("exhausted", False)}

    def _quota_today(self, storage: LocalStorage, query: dict[str, list[str]]) -> dict[str, Any]:
        return {"date": self._today(), "usage": [item for item in storage.list_documents("desktop_account_quota")
                                                if item.get("date") == self._today()]}

    def _quota_consume(self, storage: LocalStorage) -> dict[str, Any]:
        body = self._read_json()
        account_id = str(body.get("accountId") or "").strip()
        _safe_segment(account_id, "账号 ID")
        with storage._lock:
            record = self._quota_record(storage, account_id)
            try:
                limit = max(1, min(int(body.get("dailyLimit", record.get("dailyLimit", 3))), 99))
            except (ValueError, TypeError) as exc:
                raise StorageError(400, "dailyLimit 必须为整数") from exc
            record.update(generatedCount=int(record.get("generatedCount", 0)) + 1,
                          dailyLimit=limit, accountId=account_id, date=self._today())
            record["exhausted"] = record["generatedCount"] >= limit
            storage.save_document("desktop_account_quota", account_id, record,
                                  expected_revision=record.get("revision"))
        return record

    @staticmethod
    def _quota_record(storage: LocalStorage, account_id: str) -> dict[str, Any]:
        if not account_id:
            return {"generatedCount": 0, "dailyLimit": 3, "exhausted": False}
        try:
            record = storage.get_document("desktop_account_quota", account_id)
        except StorageError:
            return {"generatedCount": 0, "dailyLimit": 3, "exhausted": False}
        if record.get("date") != _Handler._today():
            return {"generatedCount": 0, "dailyLimit": int(record.get("dailyLimit", 3)), "exhausted": False,
                    "revision": record["revision"]}
        return record

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")


class LocalStorageServer:
    """在后台线程中运行本地存储 HTTP 服务。"""

    def __init__(self, root: Path, host: str = "127.0.0.1", port: int = 18081) -> None:
        self.storage = LocalStorage(root)
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        handler = type("_BoundHandler", (_Handler,), {"storage": self.storage})
        self._server = ThreadingHTTPServer((self._host, self._port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="local-storage", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def available(self, timeout: float = 0.8) -> bool:
        import socket

        try:
            with socket.create_connection((self._host, self._port), timeout=timeout):
                return True
        except OSError:
            return False


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="本地存储服务（Python 版）")
    parser.add_argument("--root", default=str(Path.home() / ".comic-drama" / "storage"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()

    server = LocalStorageServer(Path(args.root), args.host, args.port)
    server.start()
    print(f"local-storage listening on http://{args.host}:{args.port} (root={server.storage.root})")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()

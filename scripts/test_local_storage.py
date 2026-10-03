"""本地存储服务冒烟测试：验证核心接口契约。"""
import json
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from local_storage import LocalStorageServer


def call(method, url, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as error:
        resp = error
    with resp:
        return json.loads(resp.read().decode())


def main():
    root = Path(tempfile.mkdtemp())
    server = LocalStorageServer(root, port=18099)
    server.start()
    time.sleep(0.3)
    base = "http://127.0.0.1:18099"

    assert call("GET", f"{base}/api/storage/health")["data"]["status"] == "ok"
    assert call("GET", f"{base}/project/list")["data"] == []

    project = call("POST", f"{base}/project", {"name": "测试项目"})["data"]
    assert project["name"] == "测试项目" and project["id"] and project["revision"] == 1

    assert len(call("GET", f"{base}/project/list")["data"]) == 1

    updated = call("PUT", f"{base}/project/{project['id']}", {"name": "改名"})["data"]
    assert updated["name"] == "改名" and updated["revision"] == 2

    chapter = call("POST", f"{base}/project/{project['id']}/chapter", {"title": "第一章"})["data"]
    chapters = call("GET", f"{base}/project/{project['id']}/chapter/list")["data"]
    assert len(chapters) == 1 and chapters[0]["projectId"] == project["id"]

    asset = call("POST", f"{base}/asset", {"name": "角色图", "type": "image"})["data"]
    assert asset["type"] == "image"
    assert len(call("GET", f"{base}/asset/list?type=image")["data"]) == 1
    assert len(call("GET", f"{base}/asset/list?type=audio")["data"]) == 0

    video = call("POST", f"{base}/video-project", {"projectId": project["id"], "name": "任务1"})["data"]
    summary = call("GET", f"{base}/video-project/list")["data"][0]
    assert summary["assetCount"] == 0 and summary["storyboardCount"] == 0

    model = call("POST", f"{base}/api/admin/models", {
        "name": "测试模型", "modelType": "image", "modelName": "dall-e", "apiUrl": "http://x/api/"})["data"]
    assert model["apiUrl"] == "http://x/api"
    public = call("GET", f"{base}/api/admin/models/public/list?modelType=image")["data"]
    assert len(public) == 1 and "apiKey" not in public[0]

    prompt = call("POST", f"{base}/prompt", {"title": "提示词"})["data"]
    assert len(call("GET", f"{base}/prompt/list")["data"]) == 1

    call("DELETE", f"{base}/project/{project['id']}")
    assert call("GET", f"{base}/project/list")["data"] == []

    ai = call("POST", f"{base}/ai/image", {"model": "x"})
    assert ai["code"] == 500
    assert "未找到已启用的图片模型" in ai["message"]

    server.stop()
    print("ALL STORAGE SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()

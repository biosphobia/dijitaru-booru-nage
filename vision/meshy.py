"""Tiny Meshy.ai REST API client (stdlib only, no extra dependencies).

Endpoints used (see https://docs.meshy.ai):
  POST /openapi/v1/multi-image-to-3d      1-4 photos -> textured 3D model
  GET  /openapi/v1/multi-image-to-3d/:id  poll status/progress
  GET  /openapi/v1/multi-image-to-3d      list previous tasks (cloud library)
  POST /openapi/v1/rigging                add a skeleton to a humanoid model
  GET  /openapi/v1/rigging/:id            poll rigging
"""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.meshy.ai/openapi/v1"


class MeshyError(Exception):
    pass


class MeshyClient:
    def __init__(self, api_key, base=API_BASE):
        self.api_key = api_key
        self.base = base

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self.api_key)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise MeshyError("Meshy API error %d: %s" % (e.code, detail))
        except urllib.error.URLError as e:
            raise MeshyError("Meshy network error: %s" % e.reason)

    # -- multi-image to 3D --------------------------------------------------

    def create_multi_image_task(self, images_jpeg, texture_prompt="", ai_model="latest"):
        """images_jpeg: list of 1-4 JPEG byte strings. Returns task id."""
        urls = [
            "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")
            for b in images_jpeg
        ]
        body = {
            "image_urls": urls,
            "ai_model": ai_model,
            "should_remesh": True,
            "should_texture": True,
        }
        if texture_prompt:
            body["texture_prompt"] = texture_prompt[:600]
        return self._request("POST", "/multi-image-to-3d", body)["result"]

    def get_multi_image_task(self, task_id):
        return self._request("GET", "/multi-image-to-3d/" + task_id)

    def list_multi_image_tasks(self, page_size=12):
        query = urllib.parse.urlencode(
            {"page_num": 1, "page_size": page_size, "sort_by": "-created_at"}
        )
        data = self._request("GET", "/multi-image-to-3d?" + query)
        if isinstance(data, dict):
            data = data.get("result", data.get("data", []))
        return data if isinstance(data, list) else []

    # -- rigging ------------------------------------------------------------

    def create_rigging_task(self, input_task_id, height_meters=1.7):
        body = {"input_task_id": input_task_id, "height_meters": height_meters}
        return self._request("POST", "/rigging", body)["result"]

    def get_rigging_task(self, task_id):
        return self._request("GET", "/rigging/" + task_id)

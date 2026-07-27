"""Model Studio: photo capture + Meshy 3D generation, driven by UDP
commands from the game and reporting progress back as UDP events.

Commands handled (JSON, sent by the game to the command port):
  {"cmd": "capture"}                take a photo with the current camera frame
  {"cmd": "clear"}                  drop all captured photos
  {"cmd": "generate", "prompt": ""} photos -> Meshy 3D model (+ rigging)
  {"cmd": "list"}                   list previous models from the Meshy cloud

Events emitted (JSON, sent to the game's port; all carry "type": "meshy"):
  {"event": "photos", "count": 2}
  {"event": "status", "stage": "model"|"rig", "progress": 55, "message": "..."}
  {"event": "model_ready", "model_url": "...", "task_id": "...", "rigged": true}
  {"event": "models", "items": [{"task_id", "model_url", "thumbnail_url"}]}
  {"event": "error", "message": "..."}
"""

import os
import threading
import time

import cv2

from common import HERE
from meshy import MeshyClient, MeshyError

PHOTOS_DIR = os.path.join(HERE, "photos")
POLL_SECONDS = 4.0


class MeshyStudio:
    MAX_PHOTOS = 4

    def __init__(self, config, emit):
        meshy_cfg = (config or {}).get("meshy", {})
        self.api_key = meshy_cfg.get("api_key", "")
        self.ai_model = meshy_cfg.get("ai_model", "latest")
        self.rig = meshy_cfg.get("rig", True)
        self.height_meters = meshy_cfg.get("height_meters", 1.7)
        self.emit = emit  # callable(dict) -> sends event to the game
        self.photos = []  # jpeg bytes, oldest first
        self._busy = False

    # -- command entry point (called from the camera loop) -------------------

    def handle(self, cmd, frame):
        name = cmd.get("cmd", "")
        if name == "capture":
            self._capture(frame)
        elif name == "clear":
            self.photos = []
            self._event("photos", count=0)
        elif name == "generate":
            self._start(self._generate, str(cmd.get("prompt", "")))
        elif name == "list":
            self._start(self._list_models)

    # -- internals -----------------------------------------------------------

    def _event(self, event, **fields):
        payload = {"type": "meshy", "event": event}
        payload.update(fields)
        self.emit(payload)

    def _error(self, message, code=""):
        # "code" lets the game show a localized message; "message" is the
        # English detail for the console and unrecognized errors.
        print("STUDIO ERROR:", message)
        self._event("error", message=str(message), code=code)

    def _capture(self, frame):
        if frame is None:
            return self._error("No camera frame available", "capture_failed")
        if len(self.photos) >= self.MAX_PHOTOS:
            return self._error("Already have %d photos - clear first" % self.MAX_PHOTOS,
                               "photos_full")
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            return self._error("Could not encode photo", "capture_failed")
        self.photos.append(jpeg.tobytes())
        os.makedirs(PHOTOS_DIR, exist_ok=True)
        path = os.path.join(PHOTOS_DIR, "photo_%d.jpg" % len(self.photos))
        with open(path, "wb") as f:
            f.write(self.photos[-1])
        print("STUDIO: photo %d/%d captured -> %s" % (len(self.photos), self.MAX_PHOTOS, path))
        self._event("photos", count=len(self.photos))

    def _client(self):
        if not self.api_key:
            self._error('No Meshy API key - set "meshy": {"api_key": "msy-..."} in config.json',
                        "no_key")
            return None
        return MeshyClient(self.api_key)

    def _start(self, target, *args):
        if self._busy:
            return self._error("A Meshy task is already running", "busy")
        self._busy = True
        threading.Thread(target=self._run, args=(target,) + args, daemon=True).start()

    def _run(self, target, *args):
        try:
            target(*args)
        except MeshyError as e:
            self._error(e)
        except Exception as e:  # never kill the worker silently
            self._error("Unexpected: %r" % e)
        finally:
            self._busy = False

    def _poll(self, fetch, task_id, stage, label):
        while True:
            task = fetch(task_id)
            status = task.get("status", "")
            progress = int(task.get("progress", 0))
            self._event("status", stage=stage, progress=progress,
                        message="%s... %d%%" % (label, progress))
            if status == "SUCCEEDED":
                return task
            if status in ("FAILED", "CANCELED"):
                detail = (task.get("task_error") or {}).get("message", status)
                raise MeshyError("%s failed: %s" % (label, detail))
            time.sleep(POLL_SECONDS)

    def _generate(self, prompt):
        client = self._client()
        if client is None:
            return
        if not self.photos:
            return self._error("No photos yet - capture 1-4 photos first", "no_photos")

        self._event("status", stage="model", progress=0,
                    message="Uploading %d photo(s) to Meshy..." % len(self.photos))
        task_id = client.create_multi_image_task(self.photos, prompt, self.ai_model)
        task = self._poll(client.get_multi_image_task, task_id, "model", "Building 3D model")
        model_url = (task.get("model_urls") or {}).get("glb", "")
        if not model_url:
            raise MeshyError("Model finished but no GLB URL in the response")

        rigged = False
        if self.rig:
            try:
                self._event("status", stage="rig", progress=0, message="Rigging skeleton...")
                rig_id = client.create_rigging_task(task_id, self.height_meters)
                rig_task = self._poll(client.get_rigging_task, rig_id, "rig", "Rigging skeleton")
                result = rig_task.get("result", rig_task) or {}
                rigged_url = result.get("rigged_character_glb_url", "")
                if rigged_url:
                    model_url, rigged = rigged_url, True
            except MeshyError as e:
                # rigging is best-effort (needs a clear humanoid) - fall back
                self._event("status", stage="rig", progress=100,
                            message="Rigging failed (%s) - using unrigged model" % e)

        self._event("model_ready", model_url=model_url, task_id=task_id, rigged=rigged)
        print("STUDIO: model ready (%s) rigged=%s" % (task_id, rigged))

    def _list_models(self):
        client = self._client()
        if client is None:
            return
        self._event("status", stage="list", progress=0, message="Fetching your Meshy library...")
        items = []
        for task in client.list_multi_image_tasks():
            if task.get("status") != "SUCCEEDED":
                continue
            url = (task.get("model_urls") or {}).get("glb", "")
            if not url:
                continue
            items.append({
                "task_id": task.get("id", ""),
                "model_url": url,
                "thumbnail_url": task.get("thumbnail_url", ""),
            })
        self._event("models", items=items)

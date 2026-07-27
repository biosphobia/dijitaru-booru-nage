extends Node
## Model Studio: photograph a person from up to 4 angles with the tracking
## camera, send the photos to Meshy.ai (via the vision tool) to build a
## rigged 3D model, watch the progress live, and view the result rotating
## in 3D. Models live in your Meshy cloud account; the newest downloaded
## one is also cached locally so it shows up again after a restart.
##
## The vision tool (BooruVision detect) must be running - it owns the
## camera and talks to the Meshy API. This screen only sends commands and
## renders what comes back.

const CFG_PATH := "user://studio.cfg"
const CACHE_PATH := "user://latest_model.glb"
const DEFAULT_PROMPT := "a game character, colorful, friendly"

var _prompt: LineEdit
var _photos_label: Label
var _status: Label
var _progress: ProgressBar
var _holder: Node3D
var _http: HTTPRequest
var _downloading := false

func _ready() -> void:
	var ui := CanvasLayer.new()
	add_child(ui)

	var root := HBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 20)
	ui.add_child(root)

	# -- left: controls ---------------------------------------------------
	var panel := VBoxContainer.new()
	panel.custom_minimum_size = Vector2(430, 0)
	panel.add_theme_constant_override("separation", 12)
	root.add_child(panel)

	panel.add_child(_label("Model Studio", 34))
	panel.add_child(_label("1. Stand in front of the camera,\n    take 1-4 photos from different angles", 17))

	_photos_label = _label("Photos: 0 / 4", 22)
	panel.add_child(_photos_label)

	var photo_row := HBoxContainer.new()
	photo_row.add_theme_constant_override("separation", 10)
	photo_row.add_child(_button("Take photo", _on_capture))
	photo_row.add_child(_button("Clear", _on_clear))
	panel.add_child(photo_row)

	panel.add_child(_label("2. Texture prompt (how the model should look):", 17))
	_prompt = LineEdit.new()
	_prompt.text = DEFAULT_PROMPT
	_prompt.custom_minimum_size = Vector2(0, 40)
	panel.add_child(_prompt)

	panel.add_child(_button("Generate 3D model", _on_generate))
	panel.add_child(_button("Load newest from Meshy cloud", _on_load_latest))

	_progress = ProgressBar.new()
	_progress.min_value = 0
	_progress.max_value = 100
	_progress.custom_minimum_size = Vector2(0, 26)
	panel.add_child(_progress)

	_status = _label("Idle. The camera tool (BooruVision detect) must be running.", 16)
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	panel.add_child(_status)

	# -- right: 3D view ---------------------------------------------------
	var view := SubViewportContainer.new()
	view.stretch = true
	view.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	root.add_child(view)

	var vp := SubViewport.new()
	vp.own_world_3d = true
	vp.transparent_bg = true
	view.add_child(vp)

	var cam := Camera3D.new()
	vp.add_child(cam)
	cam.position = Vector3(0.0, 1.1, 2.8)

	var light := DirectionalLight3D.new()
	vp.add_child(light)
	light.rotation_degrees = Vector3(-40.0, 30.0, 0.0)

	_holder = Node3D.new()
	vp.add_child(_holder)
	cam.look_at(Vector3(0.0, 0.9, 0.0))

	_http = HTTPRequest.new()
	add_child(_http)
	_http.request_completed.connect(_on_download_done)

	BallInput.meshy_event.connect(_on_meshy_event)
	_load_prompt()
	_load_cached_model()

func _process(delta: float) -> void:
	_holder.rotate_y(0.6 * delta)

func _exit_tree() -> void:
	_save_prompt()

# -- UI helpers -----------------------------------------------------------

func _label(text: String, size: int) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", size)
	return label

func _button(text: String, on_pressed: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(0, 44)
	button.add_theme_font_size_override("font_size", 19)
	button.pressed.connect(on_pressed)
	return button

# -- commands to the vision tool ------------------------------------------

func _on_capture() -> void:
	BallInput.send_command({"cmd": "capture"})

func _on_clear() -> void:
	BallInput.send_command({"cmd": "clear"})

func _on_generate() -> void:
	_save_prompt()
	_progress.value = 0
	_status.text = "Sending photos to Meshy..."
	BallInput.send_command({"cmd": "generate", "prompt": _prompt.text})

func _on_load_latest() -> void:
	_status.text = "Asking Meshy for your saved models..."
	BallInput.send_command({"cmd": "list"})

# -- events back from the vision tool -------------------------------------

func _on_meshy_event(data: Dictionary) -> void:
	match str(data.get("event", "")):
		"photos":
			_photos_label.text = "Photos: %d / 4" % int(data.get("count", 0))
		"status":
			_status.text = str(data.get("message", ""))
			_progress.value = float(data.get("progress", 0))
		"model_ready":
			_progress.value = 100
			_download(str(data.get("model_url", "")))
		"models":
			var items: Array = data.get("items", [])
			if items.is_empty():
				_status.text = "No finished models in your Meshy account yet."
			else:
				_download(str(items[0].get("model_url", "")))
		"error":
			_status.text = "Error: %s" % str(data.get("message", ""))

# -- model download + display ---------------------------------------------

func _download(url: String) -> void:
	if url.is_empty() or _downloading:
		return
	_downloading = true
	_status.text = "Downloading model..."
	var err := _http.request(url)
	if err != OK:
		_downloading = false
		_status.text = "Download failed to start (error %d)" % err

func _on_download_done(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_downloading = false
	if code != 200 or body.is_empty():
		_status.text = "Model download failed (HTTP %d)" % code
		return
	var file := FileAccess.open(CACHE_PATH, FileAccess.WRITE)
	if file:
		file.store_buffer(body)
		file.close()
	if _show_glb(body):
		_status.text = "Model ready! It stays in your Meshy cloud account."
	else:
		_status.text = "Downloaded, but the model could not be displayed."

func _show_glb(bytes: PackedByteArray) -> bool:
	var doc := GLTFDocument.new()
	var state := GLTFState.new()
	if doc.append_from_buffer(bytes, "", state) != OK:
		return false
	var scene := doc.generate_scene(state)
	if scene == null:
		return false
	for child in _holder.get_children():
		child.queue_free()
	_holder.add_child(scene)
	return true

func _load_cached_model() -> void:
	if not FileAccess.file_exists(CACHE_PATH):
		return
	var bytes := FileAccess.get_file_as_bytes(CACHE_PATH)
	if not bytes.is_empty() and _show_glb(bytes):
		_status.text = "Showing your last model (cached). Take photos to make a new one!"

# -- prompt persistence ----------------------------------------------------

func _load_prompt() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(CFG_PATH) == OK:
		_prompt.text = str(cfg.get_value("studio", "prompt", DEFAULT_PROMPT))

func _save_prompt() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("studio", "prompt", _prompt.text)
	cfg.save(CFG_PATH)

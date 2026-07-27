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
const DEFAULT_PROMPT := "ゲームキャラクター、カラフル"

## Japanese text for error codes sent by vision/studio.py.
const ERROR_TEXT := {
	"no_key": "APIキー未設定（config.json）",
	"no_photos": "写真がありません",
	"busy": "処理中です",
	"capture_failed": "撮影失敗",
	"photos_full": "写真は4枚まで（クリアしてください）",
	"file_failed": "ファイル読込失敗",
	"key_invalid": "APIキーが無効",
	"key_save_failed": "保存失敗",
}
const STAGE_TEXT := {
	"model": "3Dモデル生成中",
	"rig": "リギング中",
	"list": "読込中",
}

var _prompt: LineEdit
var _api_key: LineEdit
var _photos_label: Label
var _status: Label
var _progress: ProgressBar
var _viewfinder: TextureRect
var _file_dialog: FileDialog
var _holder: Node3D
var _http: HTTPRequest
var _downloading := false
## Local camera via Godot's CameraServer: built-in backend on macOS/iOS,
## CameraServerExtension (bundled in exports) on Windows/Linux. If no feed
## ever appears, the vision tool streams the preview as a fallback.
## Untyped on purpose: CameraFeedExtension must not be upcast to CameraFeed.
var _local_feed = null
var _camera_ext: Object = null
var _capture_count := 0

func _ready() -> void:
	var ui := CanvasLayer.new()
	add_child(ui)

	var root := HBoxContainer.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.add_theme_constant_override("separation", 20)
	ui.add_child(root)

	# -- left: controls ---------------------------------------------------
	var panel := VBoxContainer.new()
	panel.custom_minimum_size = Vector2(560, 0)
	panel.add_theme_constant_override("separation", 14)
	root.add_child(panel)

	panel.add_child(_label("モデルスタジオ", 46))

	# live camera viewfinder (frames streamed from the vision tool)
	_viewfinder = TextureRect.new()
	_viewfinder.custom_minimum_size = Vector2(520, 292)
	_viewfinder.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_viewfinder.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	panel.add_child(_viewfinder)

	_photos_label = _label("写真 0 / 4", 30)
	panel.add_child(_photos_label)

	var photo_row := HBoxContainer.new()
	photo_row.add_theme_constant_override("separation", 10)
	photo_row.add_child(_button("撮影", _on_capture))
	photo_row.add_child(_button("ファイル追加", _on_add_file))
	photo_row.add_child(_button("クリア", _on_clear))
	panel.add_child(photo_row)

	_file_dialog = FileDialog.new()
	_file_dialog.access = FileDialog.ACCESS_FILESYSTEM
	_file_dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILES
	_file_dialog.use_native_dialog = true
	_file_dialog.filters = PackedStringArray(["*.jpg,*.jpeg,*.png ; 画像"])
	_file_dialog.files_selected.connect(_on_files_selected)
	add_child(_file_dialog)

	_prompt = LineEdit.new()
	_prompt.text = DEFAULT_PROMPT
	_prompt.placeholder_text = "テクスチャプロンプト"
	_prompt.custom_minimum_size = Vector2(0, 56)
	panel.add_child(_prompt)

	var key_row := HBoxContainer.new()
	key_row.add_theme_constant_override("separation", 10)
	_api_key = LineEdit.new()
	_api_key.secret = true
	_api_key.placeholder_text = "Meshy APIキー / JSON"
	_api_key.custom_minimum_size = Vector2(0, 56)
	_api_key.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_api_key.text_submitted.connect(func(_t: String) -> void: _on_save_key())
	key_row.add_child(_api_key)
	key_row.add_child(_button("保存", _on_save_key))
	panel.add_child(key_row)

	panel.add_child(_button("3Dモデル生成", _on_generate))
	panel.add_child(_button("クラウドから読込", _on_load_latest))

	_progress = ProgressBar.new()
	_progress.min_value = 0
	_progress.max_value = 100
	_progress.custom_minimum_size = Vector2(0, 34)
	panel.add_child(_progress)

	_status = _label("待機中", 22)
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
	if not _try_local_camera():
		BallInput.send_command({"cmd": "preview", "on": true})

	BallInput.link_changed.connect(_on_link_changed)
	_on_link_changed()

func _process(delta: float) -> void:
	_holder.rotate_y(0.6 * delta)

func _exit_tree() -> void:
	if _local_feed != null:
		_local_feed.feed_is_active = false
	else:
		BallInput.send_command({"cmd": "preview", "on": false})
	_save_prompt()

## Use the machine's camera directly through Godot. Feeds can appear
## asynchronously (permission prompts, extension enumeration), so if none
## exists yet we watch for additions and switch over when one arrives.
func _try_local_camera() -> bool:
	CameraServer.monitoring_feeds = true
	if ClassDB.class_exists("CameraServerExtension"):
		_camera_ext = ClassDB.instantiate("CameraServerExtension")
		if _camera_ext != null and _camera_ext.has_method("request_permission"):
			_camera_ext.request_permission()
	if _activate_first_feed():
		return true
	CameraServer.camera_feed_added.connect(_on_feed_added)
	return false

func _activate_first_feed() -> bool:
	var feeds := CameraServer.feeds()
	if feeds.is_empty():
		return false
	_local_feed = feeds[0]
	_local_feed.feed_is_active = true
	var tex := CameraTexture.new()
	tex.camera_feed_id = _local_feed.get_id()
	tex.camera_is_active = true
	_viewfinder.texture = tex
	return true

func _on_feed_added(_id: int) -> void:
	if _local_feed == null and _activate_first_feed():
		# local camera took over - stop the tool's preview stream
		BallInput.send_command({"cmd": "preview", "on": false})

# -- UI helpers -----------------------------------------------------------

func _label(text: String, size: int) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", size)
	return label

func _button(text: String, on_pressed: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(0, 60)
	button.add_theme_font_size_override("font_size", 26)
	button.pressed.connect(on_pressed)
	return button

# -- commands to the vision tool ------------------------------------------

func _on_capture() -> void:
	if _local_feed != null:
		_capture_local()
	else:
		BallInput.send_command({"cmd": "capture"})

## Grab a frame from the local camera, save it, and hand the file to the
## vision tool so it joins the Meshy photo set.
func _capture_local() -> void:
	var img: Image = null
	if _viewfinder.texture != null:
		img = _viewfinder.texture.get_image()
	if img == null or img.is_empty():
		# fallback: crop the on-screen viewfinder out of a window screenshot
		var shot := get_viewport().get_texture().get_image()
		if shot != null:
			img = shot.get_region(Rect2i(_viewfinder.get_global_rect()))
	if img == null or img.is_empty():
		_status.text = "撮影失敗"
		return
	if img.get_width() > 1280:
		img.resize(1280, int(img.get_height() * 1280.0 / img.get_width()),
			Image.INTERPOLATE_LANCZOS)
	img.convert(Image.FORMAT_RGB8)
	_capture_count += 1
	var path := "user://camera_%d.jpg" % _capture_count
	if img.save_jpg(path, 0.92) != OK:
		_status.text = "撮影失敗"
		return
	BallInput.send_command({"cmd": "add_file", "path": ProjectSettings.globalize_path(path)})

func _on_add_file() -> void:
	_file_dialog.popup_centered_ratio(0.7)

func _on_files_selected(paths: PackedStringArray) -> void:
	for path in paths:
		BallInput.send_command({"cmd": "add_file", "path": path})

func _on_clear() -> void:
	BallInput.send_command({"cmd": "clear"})

func _on_link_changed() -> void:
	if not BallInput.connected:
		_status.text = "カメラツール未接続"
	else:
		if _status.text == "カメラツール未接続":
			_status.text = "待機中"
		# the tool may have started after this screen opened
		if _local_feed == null:
			BallInput.send_command({"cmd": "preview", "on": true})

func _on_save_key() -> void:
	if _api_key.text.strip_edges().is_empty():
		return
	BallInput.send_command({"cmd": "set_meshy", "value": _api_key.text})

func _on_generate() -> void:
	_save_prompt()
	_progress.value = 0
	_status.text = "送信中…"
	BallInput.send_command({"cmd": "generate", "prompt": _prompt.text})

func _on_load_latest() -> void:
	_status.text = "読込中…"
	BallInput.send_command({"cmd": "list"})

# -- events back from the vision tool -------------------------------------

func _on_meshy_event(data: Dictionary) -> void:
	match str(data.get("event", "")):
		"frame":
			if _local_feed == null:
				_show_preview_frame(str(data.get("jpg", "")))
		"photos":
			_photos_label.text = "写真 %d / 4" % int(data.get("count", 0))
		"key_saved":
			_api_key.clear()
			_status.text = "APIキー保存済み"
		"status":
			var stage := str(data.get("stage", ""))
			var progress := int(data.get("progress", 0))
			_status.text = "%s… %d%%" % [STAGE_TEXT.get(stage, stage), progress]
			_progress.value = progress
		"model_ready":
			_progress.value = 100
			_download(str(data.get("model_url", "")))
		"models":
			var items: Array = data.get("items", [])
			if items.is_empty():
				_status.text = "保存済みモデルなし"
			else:
				_download(str(items[0].get("model_url", "")))
		"error":
			var code := str(data.get("code", ""))
			_status.text = ERROR_TEXT.get(code, "エラー: %s" % str(data.get("message", "")))

func _show_preview_frame(jpg_base64: String) -> void:
	if jpg_base64.is_empty():
		return
	var bytes := Marshalls.base64_to_raw(jpg_base64)
	var img := Image.new()
	if img.load_jpg_from_buffer(bytes) == OK:
		_viewfinder.texture = ImageTexture.create_from_image(img)

# -- model download + display ---------------------------------------------

func _download(url: String) -> void:
	if url.is_empty() or _downloading:
		return
	_downloading = true
	_status.text = "ダウンロード中…"
	var err := _http.request(url)
	if err != OK:
		_downloading = false
		_status.text = "ダウンロード失敗（%d）" % err

func _on_download_done(_result: int, code: int, _headers: PackedStringArray, body: PackedByteArray) -> void:
	_downloading = false
	if code != 200 or body.is_empty():
		_status.text = "ダウンロード失敗（HTTP %d）" % code
		return
	var file := FileAccess.open(CACHE_PATH, FileAccess.WRITE)
	if file:
		file.store_buffer(body)
		file.close()
	if _show_glb(body):
		_status.text = "完了"
	else:
		_status.text = "モデルを表示できません"

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
		_status.text = "前回のモデル"

# -- prompt persistence ----------------------------------------------------

func _load_prompt() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(CFG_PATH) == OK:
		_prompt.text = str(cfg.get_value("studio", "prompt", DEFAULT_PROMPT))

func _save_prompt() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("studio", "prompt", _prompt.text)
	cfg.save(CFG_PATH)

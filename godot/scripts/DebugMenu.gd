extends Node2D
## Debug mode (D from the game): the two development modes that used to be
## the main menu - the ball popup test game and Model Studio. Throwable like
## everything else, with number keys as a shortcut.

signal mode_selected(id: String)
signal closed

const RADIUS_FRAC := 0.14

func _ready() -> void:
	_build()
	get_viewport().size_changed.connect(_rebuild)

## Called by Main when a debug mode covers the menu and again when it comes
## back: a chosen target consumed itself, so the menu is built fresh.
func set_active(active: bool) -> void:
	visible = active
	process_mode = Node.PROCESS_MODE_INHERIT if active else Node.PROCESS_MODE_DISABLED
	if active:
		_rebuild()

func _rebuild() -> void:
	for child in get_children():
		child.queue_free()
	_build()

func _build() -> void:
	var vp := get_viewport_rect().size
	var short := minf(vp.x, vp.y)

	var title := Label.new()
	title.text = "デバッグ"
	title.add_theme_font_size_override("font_size", int(short * 0.08))
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	add_child(title)
	title.reset_size()
	title.position = Vector2(vp.x * 0.5 - title.size.x / 2.0, vp.y * 0.12)

	var r := short * RADIUS_FRAC
	# spread wide: the hit areas carry a lot of slack and must not overlap
	var ball := _target("ボール", Vector2(vp.x * 0.2, vp.y * 0.55), r)
	ball.hit.connect(func() -> void: mode_selected.emit("ball"))
	var studio := _target("スタジオ", Vector2(vp.x * 0.5, vp.y * 0.55), r)
	studio.hit.connect(func() -> void: mode_selected.emit("studio"))
	var back := _target("もどる", Vector2(vp.x * 0.8, vp.y * 0.55), r)
	back.hit.connect(func() -> void: closed.emit())

func _target(text: String, pos: Vector2, r: float) -> BallTarget:
	var target := BallTarget.new()
	target.position = pos
	target.radius = r
	target.label_text = text
	target.font_size = int(minf(r * 0.34, r * 1.75 / text.length()))
	add_child(target)
	return target

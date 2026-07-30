extends Node2D
## Root: runs the game, and hides the development modes behind a debug mode.
##
## The game (Game.gd) is what the wall shows and is played entirely by
## throwing balls. Pressing D opens the debug mode, whose menu holds the two
## development modes:
##   Ball Game    - the ball popup accuracy test (BallGame.gd)
##   Model Studio - photo capture -> Meshy 3D model (ModelStudio.gd)
##
## Every hit leaves a fading mark at the detected position: colored like the
## thrown ball (light blue / orange) and sized like its projected image, so
## you can check tracking accuracy against the real impact spot. Plain mouse
## clicks leave a small white mark. The mark shows the raw impact - the
## click itself is snapped to a nearby target by BallInput.
##
## Keys:
##   D      - toggle the debug mode (and back out of a debug mode)
##   1 / 2  - pick a mode in the debug menu
##   Escape - back one step, quit from the game's title screen
##   C      - toggle the calibration pattern
##   F      - toggle fullscreen

const GameScene := preload("res://scripts/Game.gd")
const DebugMenuScene := preload("res://scripts/DebugMenu.gd")
const BallGameScene := preload("res://scripts/BallGame.gd")
const ModelStudioScene := preload("res://scripts/ModelStudio.gd")
const CalibrationScene := preload("res://scripts/CalibrationScreen.gd")

const BACKGROUND := Color(0.03, 0.03, 0.09)
const MARK_COLORS := {
	"blue": Color(0.45, 0.85, 1.0),
	"lightblue": Color(0.45, 0.85, 1.0),
	"orange": Color(1.0, 0.55, 0.15),
}

var _game: Node2D
var _debug_menu: Node2D = null
var _debug_mode: Node = null
var _calibration: CanvasLayer
var _link_label: Label

func _ready() -> void:
	var bg := ColorRect.new()
	bg.color = BACKGROUND
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	# a Control that takes the mouse swallows the click before it reaches
	# the targets' picking - the backdrop must stay out of the way
	bg.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var bg_layer := CanvasLayer.new()
	bg_layer.layer = -1
	bg_layer.add_child(bg)
	add_child(bg_layer)

	_game = GameScene.new()
	add_child(_game)

	_calibration = CalibrationScene.new()
	_calibration.visible = false
	add_child(_calibration)

	# Hit marks come straight from the vision tool's events, independent of
	# the synthesized-click path, so the indicator works even if a click is
	# consumed or the input pipeline misbehaves.
	BallInput.ball_hit.connect(_on_ball_hit)

	# Persistent tracking-state indicator (tool missing / not calibrated).
	var link_layer := CanvasLayer.new()
	link_layer.layer = 5
	_link_label = Label.new()
	_link_label.add_theme_font_size_override("font_size", 24)
	_link_label.modulate = Color(1.0, 0.85, 0.4, 0.9)
	_link_label.set_anchors_and_offsets_preset(
		Control.PRESET_BOTTOM_RIGHT, Control.PRESET_MODE_MINSIZE, 20)
	_link_label.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	_link_label.grow_vertical = Control.GROW_DIRECTION_BEGIN
	link_layer.add_child(_link_label)
	add_child(link_layer)
	BallInput.link_changed.connect(_update_link)
	_update_link()

func _on_ball_hit(pos: Vector2, color: String, radius_px: float) -> void:
	if not _calibration.visible:
		_show_hit_mark(pos, MARK_COLORS.get(color, Color.WHITE), radius_px)

func _update_link() -> void:
	if not BallInput.connected:
		_link_label.text = "カメラツール未接続"
	elif not BallInput.calibrated:
		_link_label.text = "未キャリブレーション"
	else:
		_link_label.text = ""

# -- debug mode ------------------------------------------------------------

func _toggle_debug() -> void:
	if _debug_mode != null:
		_close_debug_mode()
	elif _debug_menu != null:
		_close_debug()
	else:
		_open_debug()

func _open_debug() -> void:
	_set_active(_game, false)
	_debug_menu = DebugMenuScene.new()
	_debug_menu.mode_selected.connect(_start_debug_mode)
	_debug_menu.closed.connect(_close_debug)
	add_child(_debug_menu)

func _close_debug() -> void:
	_close_debug_mode()
	if _debug_menu != null:
		_debug_menu.queue_free()
		_debug_menu = null
	_set_active(_game, true)

func _start_debug_mode(id: String) -> void:
	if _debug_mode != null:
		return
	_set_active(_debug_menu, false)
	_debug_mode = (BallGameScene if id == "ball" else ModelStudioScene).new()
	add_child(_debug_mode)

## Back out of a running debug mode to the debug menu.
func _close_debug_mode() -> void:
	if _debug_mode == null:
		return
	_debug_mode.queue_free()
	_debug_mode = null
	_set_active(_debug_menu, true)

## Hide a branch and stop it processing, so its targets stop taking hits
## (BallTarget.is_ball_active checks both). CanvasLayers ignore their
## parent's visibility, so they are hidden separately.
func _set_active(node: Node, active: bool) -> void:
	if node == null:
		return
	if node.has_method("set_active"):
		node.set_active(active)
		return
	if node is CanvasItem:
		node.visible = active
	for layer in node.find_children("*", "CanvasLayer", true, false):
		layer.visible = active
	node.process_mode = Node.PROCESS_MODE_INHERIT if active else Node.PROCESS_MODE_DISABLED

func _current_branch() -> Node:
	if _debug_mode != null:
		return _debug_mode
	if _debug_menu != null:
		return _debug_menu
	return _game

# -- input -----------------------------------------------------------------

func _unhandled_input(event: InputEvent) -> void:
	# ball hits draw their mark via the ball_hit signal; this only covers
	# real mouse clicks (no ball metadata)
	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT and not _calibration.visible \
			and not event.has_meta("ball_color"):
		_show_hit_mark(event.position, Color.WHITE, 14.0)
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_C:
				_calibration.visible = not _calibration.visible
				_set_active(_current_branch(), not _calibration.visible)
			KEY_F:
				_toggle_fullscreen()
			KEY_D:
				if not _calibration.visible:
					_toggle_debug()
			KEY_1:
				if _debug_menu != null and _debug_mode == null:
					_start_debug_mode("ball")
			KEY_2:
				if _debug_menu != null and _debug_mode == null:
					_start_debug_mode("studio")
			KEY_ESCAPE:
				if _calibration.visible:
					_calibration.visible = false
					_set_active(_current_branch(), true)
				elif _debug_mode != null:
					_close_debug_mode()
				elif _debug_menu != null:
					_close_debug()
				elif not _game.on_back():
					get_tree().quit()

## Fading mark wherever a hit landed - colored and sized like the thrown
## ball so tracking accuracy can be checked against the real impact spot.
func _show_hit_mark(pos: Vector2, color: Color, radius: float) -> void:
	var mark := HitMark.new()
	mark.position = pos
	mark.color = color
	mark.radius = clampf(radius, 6.0, 200.0)
	add_child(mark)

func _toggle_fullscreen() -> void:
	var window := get_window()
	if window.mode == Window.MODE_FULLSCREEN:
		window.mode = Window.MODE_WINDOWED
	else:
		window.mode = Window.MODE_FULLSCREEN

class HitMark extends Node2D:
	const LIFETIME := 1.4
	var color := Color.WHITE
	var radius := 14.0
	var _age := 0.0

	func _process(delta: float) -> void:
		_age += delta
		if _age >= LIFETIME:
			queue_free()
		queue_redraw()

	func _draw() -> void:
		var fade := 1.0 - _age / LIFETIME
		draw_circle(Vector2.ZERO, radius, Color(color.r, color.g, color.b, 0.7 * fade))
		draw_arc(Vector2.ZERO, radius, 0.0, TAU, 40,
			Color(color.r, color.g, color.b, fade), 2.5)

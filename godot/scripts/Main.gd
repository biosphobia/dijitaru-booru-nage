extends Node2D
## Minimal test game: a white ball appears at a random point on a solid blue
## background. A click (mouse, or a real ping pong ball hit routed through
## BallInput) pops it and a new one appears somewhere else.
##
## Every click also shows a small ripple at the cursor position, so you can
## see exactly where a thrown ball registered - even when it misses.
##
## Keys:
##   C      - toggle the calibration pattern
##   F      - toggle fullscreen
##   Escape - quit

const BallScene := preload("res://scripts/Ball.gd")
const CalibrationScene := preload("res://scripts/CalibrationScreen.gd")

const BACKGROUND := Color(0.07, 0.32, 0.85)
const RESPAWN_DELAY := 0.6

var score := 0

var _score_label: Label
var _calibration: CanvasLayer
var _ball: Area2D = null
var _respawn_left := 0.0

func _ready() -> void:
	var bg := ColorRect.new()
	bg.color = BACKGROUND
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	var bg_layer := CanvasLayer.new()
	bg_layer.layer = -1
	bg_layer.add_child(bg)
	add_child(bg_layer)

	var ui := CanvasLayer.new()
	_score_label = Label.new()
	_score_label.text = "Score: 0"
	_score_label.position = Vector2(20, 12)
	_score_label.add_theme_font_size_override("font_size", 36)
	ui.add_child(_score_label)
	var hint := Label.new()
	hint.text = "C = calibration   F = fullscreen"
	hint.add_theme_font_size_override("font_size", 18)
	hint.modulate = Color(1, 1, 1, 0.5)
	hint.position = Vector2(20, get_viewport_rect().size.y - 40)
	ui.add_child(hint)
	add_child(ui)

	_calibration = CalibrationScene.new()
	_calibration.visible = false
	add_child(_calibration)

func _process(delta: float) -> void:
	if _calibration.visible or is_instance_valid(_ball):
		return
	_respawn_left -= delta
	if _respawn_left <= 0.0:
		_spawn_ball()

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT and not _calibration.visible:
		_show_ripple(event.position)
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_C:
				_calibration.visible = not _calibration.visible
			KEY_F:
				_toggle_fullscreen()
			KEY_ESCAPE:
				get_tree().quit()

func _spawn_ball() -> void:
	var ball := BallScene.new()
	var vp := get_viewport_rect().size
	var margin := BallScene.RADIUS + 40.0
	ball.position = Vector2(
		randf_range(margin, vp.x - margin),
		randf_range(margin + 60.0, vp.y - margin)
	)
	ball.popped.connect(_on_ball_popped)
	add_child(ball)
	_ball = ball

func _on_ball_popped() -> void:
	score += 1
	_score_label.text = "Score: %d" % score
	_respawn_left = RESPAWN_DELAY

## Small expanding-ring effect wherever a click landed.
func _show_ripple(pos: Vector2) -> void:
	var ripple := Ripple.new()
	ripple.position = pos
	add_child(ripple)

func _toggle_fullscreen() -> void:
	var window := get_window()
	if window.mode == Window.MODE_FULLSCREEN:
		window.mode = Window.MODE_WINDOWED
	else:
		window.mode = Window.MODE_FULLSCREEN

class Ripple extends Node2D:
	const LIFETIME := 0.4
	var _age := 0.0

	func _process(delta: float) -> void:
		_age += delta
		if _age >= LIFETIME:
			queue_free()
		queue_redraw()

	func _draw() -> void:
		var t := _age / LIFETIME
		draw_arc(Vector2.ZERO, 14.0 + 55.0 * t, 0.0, TAU, 40,
			Color(1.0, 1.0, 1.0, 0.9 * (1.0 - t)), 5.0)

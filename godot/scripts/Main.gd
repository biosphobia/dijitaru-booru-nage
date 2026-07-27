extends Node2D
## Minimal test game: a white ball appears at a random point on a solid blue
## background. A click (mouse, or a real ping pong ball hit routed through
## BallInput) pops it and a new one appears somewhere else.
##
## Every hit leaves a fading mark at the detected position: colored like the
## thrown ball (light blue / orange) and sized like its projected image, so
## you can check tracking accuracy against the real impact spot. Plain mouse
## clicks leave a small white mark.
##
## Keys:
##   C      - toggle the calibration pattern
##   F      - toggle fullscreen
##   Escape - quit

const BallScene := preload("res://scripts/Ball.gd")
const CalibrationScene := preload("res://scripts/CalibrationScreen.gd")

const BACKGROUND := Color(0.07, 0.32, 0.85)
const RESPAWN_DELAY := 0.6
const MARK_COLORS := {
	"lightblue": Color(0.45, 0.85, 1.0),
	"orange": Color(1.0, 0.55, 0.15),
}

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
		var color_name := str(event.get_meta("ball_color", ""))
		var radius := float(event.get_meta("ball_radius_px", 14.0))
		_show_hit_mark(event.position, MARK_COLORS.get(color_name, Color.WHITE), radius)
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

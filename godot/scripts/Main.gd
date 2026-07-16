extends Node2D
## Minimal test game: colored circle targets pop up, a click (mouse or ball
## hit via BallInput) knocks them down.
##
## Keys:
##   C      - toggle the calibration pattern
##   Escape - quit

const TargetScene := preload("res://scripts/Target.gd")
const CalibrationScene := preload("res://scripts/CalibrationScreen.gd")

const MAX_TARGETS := 5
const SPAWN_INTERVAL := 1.5
const PALETTE := {
	"red": Color(0.90, 0.15, 0.15),
	"orange": Color(1.00, 0.55, 0.10),
	"yellow": Color(0.95, 0.85, 0.10),
	"green": Color(0.15, 0.75, 0.25),
	"blue": Color(0.15, 0.40, 0.90),
}

var score := 0

var _score_label: Label
var _calibration: CanvasLayer
var _targets: Node2D

func _ready() -> void:
	var bg := ColorRect.new()
	bg.color = Color(0.10, 0.10, 0.14)
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	var bg_layer := CanvasLayer.new()
	bg_layer.layer = -1
	bg_layer.add_child(bg)
	add_child(bg_layer)

	_targets = Node2D.new()
	add_child(_targets)

	var ui := CanvasLayer.new()
	_score_label = Label.new()
	_score_label.text = "Score: 0"
	_score_label.position = Vector2(20, 12)
	_score_label.add_theme_font_size_override("font_size", 36)
	ui.add_child(_score_label)
	var hint := Label.new()
	hint.text = "C = calibration screen"
	hint.add_theme_font_size_override("font_size", 18)
	hint.modulate = Color(1, 1, 1, 0.5)
	hint.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	hint.position = Vector2(20, get_viewport_rect().size.y - 40)
	ui.add_child(hint)
	add_child(ui)

	_calibration = CalibrationScene.new()
	_calibration.visible = false
	add_child(_calibration)

	var timer := Timer.new()
	timer.wait_time = SPAWN_INTERVAL
	timer.timeout.connect(_spawn_target)
	add_child(timer)
	timer.start()

	BallInput.ball_hit.connect(_on_ball_hit)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		match event.keycode:
			KEY_C:
				_calibration.visible = not _calibration.visible
			KEY_ESCAPE:
				get_tree().quit()

func _spawn_target() -> void:
	if _calibration.visible:
		return
	var alive := 0
	for child in _targets.get_children():
		if not child._falling:
			alive += 1
	if alive >= MAX_TARGETS:
		return
	var target := TargetScene.new()
	var color_name: String = PALETTE.keys().pick_random()
	target.color = PALETTE[color_name]
	var vp := get_viewport_rect().size
	var margin := TargetScene.RADIUS + 30.0
	target.position = Vector2(
		randf_range(margin, vp.x - margin),
		randf_range(margin + 60.0, vp.y - margin)
	)
	target.knocked_down.connect(_on_target_knocked)
	_targets.add_child(target)

func _on_target_knocked() -> void:
	score += 1
	_score_label.text = "Score: %d" % score

## Debug feedback: flash a small ring wherever the vision script reports a
## hit, so you can see raw hit positions even when no target is there.
func _on_ball_hit(pos: Vector2, color: String) -> void:
	var flash := HitFlash.new()
	flash.position = pos
	flash.color = PALETTE.get(color, Color.WHITE)
	add_child(flash)

class HitFlash extends Node2D:
	var color := Color.WHITE
	var _age := 0.0

	func _process(delta: float) -> void:
		_age += delta
		if _age > 0.5:
			queue_free()
		queue_redraw()

	func _draw() -> void:
		var t := _age / 0.5
		draw_arc(Vector2.ZERO, 20.0 + 60.0 * t, 0.0, TAU, 40, Color(color, 1.0 - t), 5.0)

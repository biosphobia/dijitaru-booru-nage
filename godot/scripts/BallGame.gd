extends Node2D
## Debug: the ball popup test game. A big white ball appears at a random
## point, a hit (thrown ping pong ball or mouse click) pops it, a new one
## appears. Used to check tracking accuracy, not to play.

const BallScene := preload("res://scripts/Ball.gd")

const RESPAWN_DELAY := 0.6

var score := 0

var _score_label: Label
var _ball: Area2D = null
var _respawn_left := 0.0

func _ready() -> void:
	var ui := CanvasLayer.new()
	_score_label = Label.new()
	_score_label.text = "スコア: 0"
	_score_label.position = Vector2(24, 14)
	_score_label.add_theme_font_size_override("font_size", 52)
	ui.add_child(_score_label)
	add_child(ui)

func _process(delta: float) -> void:
	if is_instance_valid(_ball):
		return
	_respawn_left -= delta
	if _respawn_left <= 0.0:
		_spawn_ball()

func _spawn_ball() -> void:
	var ball := BallScene.new()
	var vp := get_viewport_rect().size
	var margin := BallScene.RADIUS + 40.0
	ball.position = Vector2(
		randf_range(margin, vp.x - margin),
		randf_range(margin + 60.0, vp.y - margin)
	)
	ball.hit.connect(_on_ball_popped)
	add_child(ball)
	_ball = ball

func _on_ball_popped() -> void:
	score += 1
	_score_label.text = "スコア: %d" % score
	_respawn_left = RESPAWN_DELAY

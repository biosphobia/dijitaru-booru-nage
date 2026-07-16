extends Area2D
## A simple circular target. A mouse click (real or synthesized from a ball
## hit) knocks it down: it falls off the screen and is freed.

signal knocked_down

const RADIUS := 55.0
const GRAVITY := 1600.0

var color := Color.ORANGE
var _falling := false
var _velocity := Vector2.ZERO

func _ready() -> void:
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = RADIUS
	shape.shape = circle
	add_child(shape)
	input_event.connect(_on_input_event)

func _draw() -> void:
	draw_circle(Vector2.ZERO, RADIUS, color)
	draw_circle(Vector2.ZERO, RADIUS * 0.6, color.lightened(0.35))
	draw_arc(Vector2.ZERO, RADIUS, 0.0, TAU, 48, Color.WHITE, 4.0)

func _process(delta: float) -> void:
	if not _falling:
		return
	_velocity.y += GRAVITY * delta
	position += _velocity * delta
	rotation += 4.0 * delta
	modulate.a = maxf(modulate.a - delta, 0.0)
	if position.y > get_viewport_rect().size.y + RADIUS * 2.0:
		queue_free()

func _on_input_event(_viewport: Node, event: InputEvent, _shape_idx: int) -> void:
	if _falling:
		return
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		knock_down()

func knock_down() -> void:
	if _falling:
		return
	_falling = true
	_velocity = Vector2(randf_range(-150.0, 150.0), -250.0)
	# Stop catching further clicks while falling.
	input_pickable = false
	knocked_down.emit()

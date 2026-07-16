extends Area2D
## A white ball that appears at a random point. A click (real mouse or a
## ping pong ball hit via BallInput) pops it: quick grow-and-fade, then gone.

signal popped

const RADIUS := 55.0
const POP_TIME := 0.22

var _popping := false

func _ready() -> void:
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = RADIUS
	shape.shape = circle
	add_child(shape)
	input_event.connect(_on_input_event)

	# pop-in animation
	scale = Vector2.ZERO
	var tw := create_tween()
	tw.tween_property(self, "scale", Vector2.ONE, 0.18) \
		.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)

func _draw() -> void:
	draw_circle(Vector2.ZERO, RADIUS, Color(0.97, 0.97, 0.94))
	# soft shading + specular highlight so it reads as a ball
	draw_circle(Vector2(RADIUS * 0.18, RADIUS * 0.18), RADIUS * 0.78, Color(0.88, 0.88, 0.84))
	draw_circle(Vector2(-RADIUS * 0.3, -RADIUS * 0.3), RADIUS * 0.18, Color.WHITE)
	draw_arc(Vector2.ZERO, RADIUS, 0.0, TAU, 48, Color(0.75, 0.75, 0.72), 3.0)

func _on_input_event(_viewport: Node, event: InputEvent, _shape_idx: int) -> void:
	if event is InputEventMouseButton and event.pressed and event.button_index == MOUSE_BUTTON_LEFT:
		pop()

func pop() -> void:
	if _popping:
		return
	_popping = true
	input_pickable = false
	popped.emit()
	var tw := create_tween()
	tw.set_parallel(true)
	tw.tween_property(self, "scale", Vector2.ONE * 1.45, POP_TIME)
	tw.tween_property(self, "modulate:a", 0.0, POP_TIME)
	tw.chain().tween_callback(queue_free)

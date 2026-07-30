class_name BallTarget
extends Area2D
## A round target that a thrown ping pong ball can "click".
##
## Throws land off the aim point (tracking error + the throw itself), so the
## hit area is deliberately larger than the drawn circle: every target joins
## the `ball_targets` group and BallInput snaps an incoming hit to the
## nearest target whose hit radius covers it. The collision shape uses the
## same enlarged radius, so plain mouse clicks get the same slack.
##
## Set `radius` / `label_text` / `color` / `lifetime` before adding the node
## to the tree.

signal hit
## Emitted when a timed target runs out before anyone hits it.
signal expired

const GROUP := "ball_targets"
## Fallback extra hit radius as a fraction of screen width, used when the
## tuning file has nothing to say. This is the throw-error budget: at 1280
## wide it is ~77 px of slack, on top of the drawn radius.
const TOLERANCE_FRAC := 0.06
const POP_TIME := 0.22
const GROW_TIME := 0.18

var radius := 120.0
var label_text := ""
var color := Color(0.98, 0.98, 0.95)
var text_color := Color(0.04, 0.06, 0.14)
var font_size := 40
## Seconds before the target leaves on its own (0 = stays until hit).
var lifetime := 0.0
## Extra slack on top of the tuned tolerance (the aim upgrade adds to it).
var tolerance_bonus := 0.0

var _left := 0.0
var _age := 0.0
var _taken := false

func _ready() -> void:
	add_to_group(GROUP)
	_left = lifetime

	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = hit_radius()
	shape.shape = circle
	add_child(shape)
	input_event.connect(_on_input_event)

	if not label_text.is_empty():
		var label := Label.new()
		label.text = label_text
		label.add_theme_font_size_override("font_size", font_size)
		label.add_theme_color_override("font_color", text_color)
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		label.size = Vector2(radius * 2.0, radius * 2.0)
		label.position = -Vector2(radius, radius)
		label.mouse_filter = Control.MOUSE_FILTER_IGNORE
		add_child(label)

	scale = Vector2.ZERO
	var tw := create_tween()
	tw.tween_property(self, "scale", Vector2.ONE, GROW_TIME) \
		.set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)

func _process(delta: float) -> void:
	_age += delta
	if lifetime > 0.0 and not _taken:
		_left -= delta
		if _left <= 0.0:
			_taken = true
			input_pickable = false
			expired.emit()
			_vanish(0.6)
			return
	queue_redraw()

## Radius a throw may land within and still count as a hit.
func hit_radius() -> float:
	var width := 1280.0
	if is_inside_tree():
		width = get_viewport_rect().size.x
	var frac := float(Tuning.n("aim.tolerance", TOLERANCE_FRAC)) + tolerance_bonus
	return radius + frac * width

# -- contract used by BallInput's hit snapping ----------------------------

func ball_center() -> Vector2:
	return global_position

func ball_hit_radius() -> float:
	return hit_radius()

func is_ball_active() -> bool:
	return not _taken and not is_queued_for_deletion() \
		and is_visible_in_tree() and can_process()

# -------------------------------------------------------------------------

## Mouse clicks go through the same picker as thrown balls, so overlapping
## hit areas resolve to one target instead of every target under the point.
func _on_input_event(_viewport: Node, event: InputEvent, _shape_idx: int) -> void:
	if not is_ball_active() or event.has_meta("ball_dispatched"):
		return
	if event is InputEventMouseButton and event.pressed \
			and event.button_index == MOUSE_BUTTON_LEFT \
			and BallInput.pick_target(event.position) == self:
		take()

## Count this target as hit: fires `hit`, then grows and fades away.
func take() -> void:
	if _taken:
		return
	_taken = true
	input_pickable = false
	hit.emit()
	_vanish(1.45)

func _vanish(end_scale: float) -> void:
	var tw := create_tween()
	tw.set_parallel(true)
	tw.tween_property(self, "scale", Vector2.ONE * end_scale, POP_TIME)
	tw.tween_property(self, "modulate:a", 0.0, POP_TIME)
	tw.chain().tween_callback(queue_free)

func _draw() -> void:
	var r := radius * (1.0 + 0.02 * sin(_age * 3.5))
	# halo showing the throw slack, plus a hard rim: everything has to read
	# across a bright room, where low-contrast edges disappear
	draw_circle(Vector2.ZERO, hit_radius(), Color(color.r, color.g, color.b, 0.18))
	draw_arc(Vector2.ZERO, hit_radius(), 0.0, TAU, 64,
		Color(color.r, color.g, color.b, 0.5), 3.0)
	draw_circle(Vector2.ZERO, r, color)
	draw_circle(Vector2.ZERO, r * 0.74, color.darkened(0.18))
	draw_circle(Vector2.ZERO, r * 0.42, color)
	draw_arc(Vector2.ZERO, r, 0.0, TAU, 64, color.darkened(0.5), 6.0)
	if lifetime > 0.0:
		var frac := clampf(_left / lifetime, 0.0, 1.0)
		draw_arc(Vector2.ZERO, r + 14.0, -PI / 2.0, -PI / 2.0 + TAU * frac, 64,
			Color(1.0, 1.0, 1.0, 0.8), 6.0)

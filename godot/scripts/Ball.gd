extends BallTarget
## The debug ball game's white ball. A BallTarget with a ball drawn over it:
## generous hit slack, just a different look. Bigger than the game's targets
## because it is the one thing on an otherwise empty screen.

const RADIUS := 160.0

func _ready() -> void:
	radius = RADIUS
	super()

func _draw() -> void:
	# throw slack, same halo as any other target
	draw_circle(Vector2.ZERO, hit_radius(), Color(1.0, 1.0, 1.0, 0.09))
	draw_circle(Vector2.ZERO, RADIUS, Color(0.97, 0.97, 0.94))
	# soft shading + specular highlight so it reads as a ball
	draw_circle(Vector2(RADIUS * 0.18, RADIUS * 0.18), RADIUS * 0.78, Color(0.88, 0.88, 0.84))
	draw_circle(Vector2(-RADIUS * 0.3, -RADIUS * 0.3), RADIUS * 0.18, Color.WHITE)
	draw_arc(Vector2.ZERO, RADIUS, 0.0, TAU, 48, Color(0.75, 0.75, 0.72), 3.0)

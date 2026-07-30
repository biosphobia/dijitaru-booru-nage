class_name Enemy
extends BallTarget
## An alien drifting down towards the ship. A BallTarget, so it carries the
## same throw slack as everything else and BallInput routes hits to the one
## the ball landed nearest.
##
## Stats come from Tuning ("enemies" in game.json); behaviour per type is
## here. A `enemy_<type>` image in game_assets replaces the drawn art -
## and is where the Meshy models will plug in later, rendered to a texture
## the same way.

signal damaged
signal escaped

const SHIELD_COLOR := Color(0.45, 0.9, 1.0)

var type := "grunt"
var hp := 1
var max_hp := 1
var coin_value := 1
var fall_speed := 60.0   # px per second, downward
var ship_y := 600.0
var hit_damage := 1
var shielded := false
var frozen := 0.0        # seconds left of the time-stop upgrade

var _sway := 0.0
var _sway_amp := 0.0
var _base_x := 0.0
var _flash := 0.0
var _tex: Texture2D = null

## Fills in stats for `enemy_type` and returns itself, so a caller can
## configure and add in one go. Must be called before entering the tree.
func setup(enemy_type: String, radius_px: float, speed_px: float) -> Enemy:
	type = enemy_type
	var stats := Tuning.enemy(type)
	hp = int(stats.get("hp", 1))
	max_hp = hp
	coin_value = int(stats.get("coins", 1))
	radius = radius_px
	fall_speed = speed_px
	shielded = type == "shield"
	color = _type_color()
	match type:
		"swift":
			_sway_amp = radius * 1.6
		"splitter":
			_sway_amp = radius * 0.5
		"boss":
			_sway_amp = radius * 0.7
	return self

func _ready() -> void:
	super()
	_base_x = position.x
	_sway = randf() * TAU
	_tex = Assets.texture("enemy_" + type)

## Still coming, whether or not it can be hit yet.
func is_alive() -> bool:
	return not _taken and not is_queued_for_deletion()

## Aliens enter from above the screen; until one is actually in view a
## throw must not be able to find it, or balls thrown high pick off
## enemies nobody can see.
func is_ball_active() -> bool:
	return super() and position.y > radius * 0.9

func _process(delta: float) -> void:
	super(delta)
	if _taken:
		return
	if _flash > 0.0:
		_flash = maxf(0.0, _flash - delta)
	if frozen > 0.0:
		frozen -= delta
		return
	position.y += fall_speed * delta
	if _sway_amp > 0.0:
		_sway += delta * 1.7
		position.x = _base_x + sin(_sway) * _sway_amp
	if position.y >= ship_y:
		_taken = true
		input_pickable = false
		escaped.emit()
		_vanish(0.5)

## A blue ball landed on this alien. Armour and shields eat hits before the
## alien does; only the killing blow runs BallTarget's take (which fires
## `hit`, the signal the game counts as a kill).
func take() -> void:
	if _taken:
		return
	if shielded:
		shielded = false
		_flash = 0.2
		damaged.emit()
		return
	hp -= hit_damage
	if hp > 0:
		_flash = 0.2
		damaged.emit()
		return
	super()

## Damage from a fireball. Everything but a boss dies outright.
func blast(amount: int) -> void:
	if _taken:
		return
	shielded = false
	if type != "boss":
		hp = 0
		super.take()
		return
	hp -= amount
	if hp <= 0:
		super.take()
	else:
		_flash = 0.3
		damaged.emit()

func _type_color() -> Color:
	match type:
		"swift": return Color(0.55, 1.0, 0.55)
		"armor": return Color(0.72, 0.76, 0.85)
		"splitter": return Color(1.0, 0.62, 0.95)
		"shield": return Color(0.5, 0.8, 1.0)
		"mini": return Color(1.0, 0.75, 0.98)
		"boss": return Color(1.0, 0.45, 0.35)
		_: return Color(0.65, 0.85, 0.4)

func _draw() -> void:
	# throw slack, as a thin ring: a filled disc reads as a dirty shadow
	# against the black of space
	draw_arc(Vector2.ZERO, hit_radius(), 0.0, TAU, 48,
		Color(color.r, color.g, color.b, 0.16), 2.0)
	var body := color
	if _flash > 0.0:
		body = color.lerp(Color.WHITE, _flash / 0.2)
	if _tex != null:
		var side := radius * 2.2
		draw_texture_rect(_tex, Rect2(-Vector2(side, side) / 2.0, Vector2(side, side)),
			false, Color(1, 1, 1, 1).lerp(Color.WHITE, _flash / 0.2))
	else:
		_draw_alien(body)
	if shielded:
		draw_arc(Vector2.ZERO, radius * 1.18, PI * 0.15, PI * 0.85, 32,
			Color(SHIELD_COLOR.r, SHIELD_COLOR.g, SHIELD_COLOR.b, 0.9), 7.0)
	# close to the hull: ring the alarm so the player knows what to hit next
	if position.y > ship_y - radius * 2.4:
		var pulse := 0.5 + 0.5 * sin(_age * 9.0)
		draw_arc(Vector2.ZERO, radius * 1.3, 0.0, TAU, 40,
			Color(1.0, 0.25, 0.2, 0.35 + 0.5 * pulse), 6.0)
	if max_hp > 1:
		_draw_hp()

func _draw_alien(body: Color) -> void:
	var wobble := 1.0 + 0.04 * sin(_age * 3.0)
	var r := radius * wobble
	# tentacles
	var arms := 5 if type != "boss" else 8
	for i in arms:
		var ang := PI * (0.15 + 0.7 * i / float(arms - 1))
		var base := Vector2.RIGHT.rotated(ang) * r * 0.85
		var tip := base + Vector2(sin(_age * 4.0 + i) * r * 0.12, r * 0.55)
		draw_line(base, tip, body.darkened(0.25), r * 0.16)
	draw_circle(Vector2.ZERO, r, body)
	draw_circle(Vector2(0, -r * 0.08), r * 0.78, body.lightened(0.12))
	# armour plating
	if type == "armor":
		draw_arc(Vector2.ZERO, r * 0.92, 0.0, TAU, 40, body.darkened(0.45), r * 0.14)
	# eyes
	var eyes := 1 if type in ["swift", "mini"] else 2
	var eye_r := r * (0.3 if eyes == 1 else 0.22)
	for i in eyes:
		var ex := 0.0 if eyes == 1 else (i * 2.0 - 1.0) * r * 0.32
		var eye := Vector2(ex, -r * 0.12)
		draw_circle(eye, eye_r, Color.WHITE)
		draw_circle(eye + Vector2(0, eye_r * 0.18), eye_r * 0.52, Color(0.06, 0.05, 0.12))
	# mouth
	if type == "boss" or type == "armor":
		draw_arc(Vector2(0, r * 0.34), r * 0.34, PI * 0.1, PI * 0.9, 20,
			Color(0.1, 0.05, 0.1), r * 0.09)

func _draw_hp() -> void:
	var w := radius * 1.5
	var y := -radius - 22.0
	var frac := clampf(float(hp) / float(max_hp), 0.0, 1.0)
	draw_rect(Rect2(-w / 2.0, y, w, 12.0), Color(0, 0, 0, 0.45))
	draw_rect(Rect2(-w / 2.0, y, w * frac, 12.0), Color(1.0, 0.35, 0.3))
	draw_rect(Rect2(-w / 2.0, y, w, 12.0), Color(1, 1, 1, 0.5), false, 2.0)

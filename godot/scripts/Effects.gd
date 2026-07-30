class_name Effects
extends Object
## Throwaway visual bits: the starfield behind everything, explosions,
## the fireball blast front, floating coin numbers, screen shake.
##
## Each one draws itself procedurally and can be replaced by an image
## dropped into game_assets/images (see GameAssets.gd).

## Slowly drifting starfield. Replaced wholesale by a `background` image.
class Starfield extends Node2D:
	var _stars: Array[Vector3] = []  # x, y, speed
	var _size := Vector2(1280, 720)
	var _bg: Texture2D = null

	func _ready() -> void:
		z_index = -10
		_bg = Assets.texture("background")
		_resize()
		get_viewport().size_changed.connect(_resize)

	func _resize() -> void:
		_size = get_viewport_rect().size
		_stars.clear()
		for i in 90:
			_stars.append(Vector3(
				randf() * _size.x, randf() * _size.y, randf_range(6.0, 34.0)))

	func _process(delta: float) -> void:
		if _bg != null:
			return
		for i in _stars.size():
			var s := _stars[i]
			s.y += s.z * delta
			if s.y > _size.y:
				s = Vector3(randf() * _size.x, -4.0, s.z)
			_stars[i] = s
		queue_redraw()

	func _draw() -> void:
		if _bg != null:
			draw_texture_rect(_bg, Rect2(Vector2.ZERO, _size), false)
			return
		# bright and chunky: thin dim stars vanish on a lit-room projection
		for s in _stars:
			var bright := 0.55 + s.z / 60.0
			draw_circle(Vector2(s.x, s.y), 1.6 + s.z / 16.0,
				Color(0.85, 0.92, 1.0, bright))

## Expanding burst where an alien died.
class Explosion extends Node2D:
	var radius := 80.0
	var color := Color(1.0, 0.75, 0.25)
	var _age := 0.0
	var _life := 0.45
	var _tex: Texture2D = null

	func _ready() -> void:
		z_index = 5
		_tex = Assets.texture("explosion")

	func _process(delta: float) -> void:
		_age += delta
		if _age >= _life:
			queue_free()
			return
		queue_redraw()

	func _draw() -> void:
		var t := _age / _life
		var r := radius * (0.5 + 1.3 * t)
		var fade := 1.0 - t
		if _tex != null:
			var side := r * 2.4
			draw_texture_rect(_tex, Rect2(-Vector2(side, side) / 2.0, Vector2(side, side)),
				false, Color(1, 1, 1, fade))
			return
		draw_circle(Vector2.ZERO, r, Color(color.r, color.g, color.b, 0.35 * fade))
		draw_arc(Vector2.ZERO, r, 0.0, TAU, 48, Color(1, 1, 1, fade), 5.0 * fade + 1.0)
		for i in 8:
			var ang := TAU * i / 8.0 + radius
			var from := Vector2.RIGHT.rotated(ang) * r * 0.7
			var to := Vector2.RIGHT.rotated(ang) * r * 1.25
			draw_line(from, to, Color(color.r, color.g, color.b, fade), 4.0)

## The orange ball's blast front, sweeping out from where it landed.
class Shockwave extends Node2D:
	var speed := 1600.0
	var max_radius := 1600.0
	var _r := 0.0
	var _tex: Texture2D = null

	func _ready() -> void:
		z_index = 8
		_tex = Assets.texture("fireball")

	func _process(delta: float) -> void:
		_r += speed * delta
		if _r >= max_radius:
			queue_free()
			return
		queue_redraw()

	func _draw() -> void:
		var t := _r / max_radius
		var fade := 1.0 - t
		if _tex != null:
			var side := _r * 2.0
			draw_texture_rect(_tex, Rect2(-Vector2(side, side) / 2.0, Vector2(side, side)),
				false, Color(1, 1, 1, fade))
			return
		draw_circle(Vector2.ZERO, _r, Color(1.0, 0.45, 0.1, 0.22 * fade))
		draw_arc(Vector2.ZERO, _r, 0.0, TAU, 72, Color(1.0, 0.85, 0.4, fade), 16.0 * fade + 3.0)
		draw_arc(Vector2.ZERO, _r * 0.82, 0.0, TAU, 72, Color(1.0, 0.5, 0.15, 0.7 * fade), 10.0)

## Number that floats up and fades - coins earned, damage taken.
class FloatText extends Node2D:
	var text := ""
	var color := Color(1.0, 0.85, 0.3)
	var font_size := 40
	var _label: Label
	var _age := 0.0
	var _life := 1.0

	func _ready() -> void:
		z_index = 9
		_label = Label.new()
		_label.text = text
		_label.add_theme_font_size_override("font_size", font_size)
		_label.add_theme_color_override("font_color", color)
		_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		add_child(_label)
		_label.reset_size()
		_label.position = Vector2(-_label.size.x / 2.0, -_label.size.y / 2.0)

	func _process(delta: float) -> void:
		_age += delta
		if _age >= _life:
			queue_free()
			return
		position.y -= 46.0 * delta
		modulate.a = 1.0 - pow(_age / _life, 2.0)

## Brief full-screen colour wash - hull damage, fireball flash.
class Flash extends Node2D:
	var color := Color(1.0, 0.2, 0.2, 0.45)
	var _age := 0.0
	var _life := 0.35

	func _ready() -> void:
		z_index = 20

	func _process(delta: float) -> void:
		_age += delta
		if _age >= _life:
			queue_free()
			return
		queue_redraw()

	func _draw() -> void:
		var fade := 1.0 - _age / _life
		var size := get_viewport_rect().size
		draw_rect(Rect2(Vector2.ZERO, size),
			Color(color.r, color.g, color.b, color.a * fade))

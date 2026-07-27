extends Node2D
## Main menu / mode manager. Two modes:
##   Ball Game    - the ball popup test game (BallGame.gd)
##   Model Studio - photo capture -> Meshy 3D model (ModelStudio.gd)
##
## Every hit leaves a fading mark at the detected position: colored like the
## thrown ball (light blue / orange) and sized like its projected image, so
## you can check tracking accuracy against the real impact spot. Plain mouse
## clicks leave a small white mark.
##
## Keys:
##   1 / 2  - pick a mode from the menu
##   Escape - back to menu (from a mode), quit (from the menu)
##   C      - toggle the calibration pattern
##   F      - toggle fullscreen

const BallGameScene := preload("res://scripts/BallGame.gd")
const ModelStudioScene := preload("res://scripts/ModelStudio.gd")
const CalibrationScene := preload("res://scripts/CalibrationScreen.gd")

const BACKGROUND := Color(0.07, 0.32, 0.85)
const MARK_COLORS := {
	"lightblue": Color(0.45, 0.85, 1.0),
	"orange": Color(1.0, 0.55, 0.15),
}

var _menu: CanvasLayer
var _mode: Node = null
var _calibration: CanvasLayer

func _ready() -> void:
	var bg := ColorRect.new()
	bg.color = BACKGROUND
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	var bg_layer := CanvasLayer.new()
	bg_layer.layer = -1
	bg_layer.add_child(bg)
	add_child(bg_layer)

	_menu = CanvasLayer.new()
	var box := VBoxContainer.new()
	box.set_anchors_preset(Control.PRESET_CENTER)
	box.grow_horizontal = Control.GROW_DIRECTION_BOTH
	box.grow_vertical = Control.GROW_DIRECTION_BOTH
	box.add_theme_constant_override("separation", 18)
	box.alignment = BoxContainer.ALIGNMENT_CENTER
	_menu.add_child(box)

	var title := Label.new()
	title.text = "Dijitaru Booru Nage"
	title.add_theme_font_size_override("font_size", 52)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(title)

	box.add_child(_menu_button("Ball Game  (1)", func() -> void: _start_mode(BallGameScene)))
	box.add_child(_menu_button("Model Studio  (2)", func() -> void: _start_mode(ModelStudioScene)))

	var hint := Label.new()
	hint.text = "C = calibration    F = fullscreen    Esc = back / quit"
	hint.add_theme_font_size_override("font_size", 18)
	hint.modulate = Color(1, 1, 1, 0.6)
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	box.add_child(hint)
	add_child(_menu)

	_calibration = CalibrationScene.new()
	_calibration.visible = false
	add_child(_calibration)

func _menu_button(text: String, on_pressed: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(340, 64)
	button.add_theme_font_size_override("font_size", 28)
	button.pressed.connect(on_pressed)
	return button

func _start_mode(scene: GDScript) -> void:
	if _mode != null:
		return
	_menu.visible = false
	_mode = scene.new()
	add_child(_mode)

func _back_to_menu() -> void:
	if _mode != null:
		_mode.queue_free()
		_mode = null
	_menu.visible = true

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
				if _mode != null:
					_mode.set_process(not _calibration.visible)
			KEY_F:
				_toggle_fullscreen()
			KEY_1:
				if _menu.visible:
					_start_mode(BallGameScene)
			KEY_2:
				if _menu.visible:
					_start_mode(ModelStudioScene)
			KEY_ESCAPE:
				if _calibration.visible:
					_calibration.visible = false
				elif _mode != null:
					_back_to_menu()
				else:
					get_tree().quit()

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

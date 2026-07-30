extends CanvasLayer
## Full-screen calibration pattern: a white background with a 4x3 grid of
## ArUco markers (DICT_4X4_50, ids 0-11, row-major). The vision tool
## (vision/calibrate.py) detects them and fits the camera -> screen
## mapping; a grid of points keeps it accurate from low camera angles and
## on distorted screens, and a partial view of the grid is enough.
##
## Marker CENTERS sit at (GRID_XS[col], GRID_YS[row]) in normalized screen
## coordinates with id = row * 4 + col - vision/common.py mirrors this
## layout and both must stay in sync.

const GRID_XS := [0.14, 0.38, 0.62, 0.86]
const GRID_YS := [0.15, 0.50, 0.85]

var _rects: Array[TextureRect] = []
var _label: Label

func _ready() -> void:
	layer = 10

	var bg := ColorRect.new()
	bg.color = Color.WHITE
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	for id in GRID_XS.size() * GRID_YS.size():
		var rect := TextureRect.new()
		rect.texture = load("res://assets/aruco_%d.png" % id)
		rect.stretch_mode = TextureRect.STRETCH_SCALE
		rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		add_child(rect)
		_rects.append(rect)

	_label = Label.new()
	_label.text = "キャリブレーション（C で戻る）"
	_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_label.add_theme_color_override("font_color", Color.BLACK)
	_label.add_theme_font_size_override("font_size", 34)
	add_child(_label)

	get_viewport().size_changed.connect(_layout)
	_layout()

func _layout() -> void:
	var vp := get_viewport().get_visible_rect().size
	# The marker itself fills 80% of the texture (the rest is the white
	# quiet zone the detector needs).
	var side := 0.15 * minf(vp.x, vp.y)
	for row in GRID_YS.size():
		for col in GRID_XS.size():
			var rect := _rects[row * GRID_XS.size() + col]
			rect.size = Vector2(side, side)
			rect.position = Vector2(GRID_XS[col] * vp.x, GRID_YS[row] * vp.y) - rect.size / 2.0
	# label in the horizontal band between the first two marker rows
	_label.reset_size()
	_label.position = Vector2(vp.x / 2.0 - _label.size.x / 2.0, vp.y * 0.325 - _label.size.y / 2.0)

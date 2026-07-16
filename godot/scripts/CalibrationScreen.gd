extends CanvasLayer
## Full-screen calibration pattern: a white background with four ArUco
## markers (DICT_4X4_50, ids 0..3). The vision script (vision/calibrate.py)
## detects these markers in the camera image and computes the homography.
##
## Marker CENTERS sit at these normalized screen coordinates and the ids
## must stay in this order — vision/calibrate.py relies on it:
##   id 0: (0.1, 0.1)  top-left       id 1: (0.9, 0.1)  top-right
##   id 2: (0.9, 0.9)  bottom-right   id 3: (0.1, 0.9)  bottom-left

const MARKER_CENTERS := {
	0: Vector2(0.1, 0.1),
	1: Vector2(0.9, 0.1),
	2: Vector2(0.9, 0.9),
	3: Vector2(0.1, 0.9),
}

var _rects: Array[TextureRect] = []

func _ready() -> void:
	layer = 10

	var bg := ColorRect.new()
	bg.color = Color.WHITE
	bg.set_anchors_preset(Control.PRESET_FULL_RECT)
	add_child(bg)

	for id in MARKER_CENTERS:
		var rect := TextureRect.new()
		rect.texture = load("res://assets/aruco_%d.png" % id)
		rect.stretch_mode = TextureRect.STRETCH_SCALE
		rect.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		add_child(rect)
		_rects.append(rect)

	var label := Label.new()
	label.text = "CALIBRATION\nRun vision/calibrate.py, then press C to return to the game"
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.add_theme_color_override("font_color", Color.BLACK)
	label.add_theme_font_size_override("font_size", 28)
	label.set_anchors_preset(Control.PRESET_CENTER)
	label.grow_horizontal = Control.GROW_DIRECTION_BOTH
	label.grow_vertical = Control.GROW_DIRECTION_BOTH
	add_child(label)

	get_viewport().size_changed.connect(_layout)
	_layout()

func _layout() -> void:
	var vp := get_viewport().get_visible_rect().size
	# The marker itself fills 80% of the texture (the rest is the white
	# quiet zone), so this puts the black marker at ~14% of the short side.
	var side := 0.18 * minf(vp.x, vp.y)
	var i := 0
	for id in MARKER_CENTERS:
		var rect := _rects[i]
		rect.size = Vector2(side, side)
		rect.position = MARKER_CENTERS[id] * vp - rect.size / 2.0
		i += 1

extends Node
## Autoload singleton that listens for ball-hit packets from the vision
## script (vision/detect.py) and turns them into mouse clicks.
##
## Packet format (UDP, JSON, one packet per hit):
##   {"type": "hit", "x": 0.42, "y": 0.61, "color": "orange"}
## x/y are normalized game coordinates in [0, 1] (0,0 = top-left).

signal ball_hit(position: Vector2, color: String)

const PORT := 4242

var _socket := PacketPeerUDP.new()

func _ready() -> void:
	var err := _socket.bind(PORT, "127.0.0.1")
	if err != OK:
		push_error("BallInput: could not bind UDP port %d (error %d)" % [PORT, err])
	else:
		print("BallInput: listening for hits on udp://127.0.0.1:%d" % PORT)

func _process(_delta: float) -> void:
	while _socket.get_available_packet_count() > 0:
		var text := _socket.get_packet().get_string_from_utf8()
		var data: Variant = JSON.parse_string(text)
		if typeof(data) != TYPE_DICTIONARY or data.get("type", "") != "hit":
			continue
		var norm := Vector2(
			clampf(float(data.get("x", 0.5)), 0.0, 1.0),
			clampf(float(data.get("y", 0.5)), 0.0, 1.0)
		)
		var pos := norm * get_viewport().get_visible_rect().size
		ball_hit.emit(pos, str(data.get("color", "unknown")))
		_send_click(pos)

## Synthesize a left-click press+release so anything that reacts to normal
## mouse clicks (buttons, Area2D input_event, _unhandled_input) just works.
func _send_click(pos: Vector2) -> void:
	var press := InputEventMouseButton.new()
	press.button_index = MOUSE_BUTTON_LEFT
	press.pressed = true
	press.position = pos
	press.global_position = pos
	Input.parse_input_event(press)

	var release := InputEventMouseButton.new()
	release.button_index = MOUSE_BUTTON_LEFT
	release.pressed = false
	release.position = pos
	release.global_position = pos
	Input.parse_input_event(release)

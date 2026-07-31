extends Node
## Autoload singleton that listens for ball-hit packets from the vision
## script (vision/detect.py) and turns them into mouse clicks.
##
## Packet format (UDP, JSON, one packet per hit):
##   {"type": "hit", "x": 0.42, "y": 0.61, "color": "orange"}
## x/y are normalized game coordinates in [0, 1] (0,0 = top-left).

signal ball_hit(position: Vector2, color: String, radius_px: float)
## Model Studio events from the vision tool (photo counts, Meshy progress,
## finished models). See vision/studio.py for the event dictionary shapes.
signal meshy_event(data: Dictionary)
## Emitted when `connected` or `calibrated` changes.
signal link_changed

const PORT := 4242
const CMD_PORT := 4243
## Fallback mark radius (fraction of screen width) when a packet has no "r".
const DEFAULT_RADIUS_FRAC := 0.012

## Whether the vision tool is running (answers pings) and whether it has a
## wall calibration (without one, ball hits are disabled tool-side).
var connected := false
var calibrated := false

var _socket := PacketPeerUDP.new()
var _cmd_socket := PacketPeerUDP.new()
var _last_pong_ms := 0

func _ready() -> void:
	var err := _socket.bind(PORT, "127.0.0.1")
	if err != OK:
		push_error("BallInput: could not bind UDP port %d (error %d)" % [PORT, err])
	else:
		print("BallInput: listening for hits on udp://127.0.0.1:%d" % PORT)
	_cmd_socket.connect_to_host("127.0.0.1", CMD_PORT)

	var ping_timer := Timer.new()
	ping_timer.wait_time = 1.5
	ping_timer.timeout.connect(_ping)
	add_child(ping_timer)
	ping_timer.start()
	_ping()

## Send a Model Studio command to the vision tool (capture/clear/generate/list).
func send_command(cmd: Dictionary) -> void:
	_cmd_socket.put_packet(JSON.stringify(cmd).to_utf8_buffer())

func _ping() -> void:
	send_command({"cmd": "ping"})
	if connected and Time.get_ticks_msec() - _last_pong_ms > 5000:
		connected = false
		link_changed.emit()

func _on_pong(data: Dictionary) -> void:
	_last_pong_ms = Time.get_ticks_msec()
	var cal := bool(data.get("calibrated", false))
	if not connected or cal != calibrated:
		connected = true
		calibrated = cal
		link_changed.emit()

func _process(_delta: float) -> void:
	while _socket.get_available_packet_count() > 0:
		var text := _socket.get_packet().get_string_from_utf8()
		var data: Variant = JSON.parse_string(text)
		if typeof(data) != TYPE_DICTIONARY:
			continue
		if data.get("type", "") == "meshy":
			if data.get("event", "") == "pong":
				_on_pong(data)
			meshy_event.emit(data)
			continue
		if data.get("type", "") != "hit":
			continue
		var vp := get_viewport().get_visible_rect().size
		var norm := Vector2(
			clampf(float(data.get("x", 0.5)), 0.0, 1.0),
			clampf(float(data.get("y", 0.5)), 0.0, 1.0)
		)
		var pos := norm * vp
		var r_frac := clampf(float(data.get("r", 0.0)), 0.0, 0.2)
		if r_frac <= 0.0:
			r_frac = DEFAULT_RADIUS_FRAC
		var radius_px := r_frac * vp.x
		var color := str(data.get("color", "unknown"))
		# The mark shows where the ball really landed (tracking accuracy);
		# the click is snapped to the target the throw was aiming at.
		ball_hit.emit(pos, color, radius_px)
		var target := pick_target(pos)
		if target != null:
			# Tell the target directly: a throw must never be swallowed by
			# whatever Control happens to sit under the impact point.
			pos = target.ball_center()
			target.take()
		_send_click(pos, color, radius_px, target != null)

## Throws land off the aim point, so a hit near a target counts as a hit
## on it. Eligible = the target's hit area covers the impact; among those
## the winner is the one whose VISIBLE edge is closest to the impact -
## players aim at what they see, so a small alien right next to the ball
## must beat a big one whose halo merely reaches further. Nodes in the
## `ball_targets` group opt in by providing ball_center() /
## ball_hit_radius() / is_ball_active() / take() (and optionally
## ball_draw_radius()) - see BallTarget.gd. Returns null when the impact
## is not near any target.
func pick_target(pos: Vector2) -> Node:
	var best: Node = null
	var best_edge := INF
	for node in get_tree().get_nodes_in_group("ball_targets"):
		if not node.has_method("ball_hit_radius") or not node.has_method("is_ball_active"):
			continue
		if not node.is_ball_active():
			continue
		var radius: float = node.ball_hit_radius()
		if radius <= 0.0:
			continue
		var dist: float = node.ball_center().distance_to(pos)
		if dist > radius:
			continue
		var drawn: float = node.ball_draw_radius() \
			if node.has_method("ball_draw_radius") else 0.0
		var edge := dist - drawn
		if edge < best_edge:
			best_edge = edge
			best = node
	return best

## Synthesize a left-click press+release so anything that reacts to normal
## mouse clicks (buttons, Area2D input_event, _unhandled_input) just works.
## Ball info rides along as event metadata so the game can draw the hit
## mark in the ball's color and at its real projected size. `dispatched`
## marks a hit a target already took, so no second target picks it up.
func _send_click(pos: Vector2, color: String, radius_px: float,
		dispatched := false) -> void:
	var press := InputEventMouseButton.new()
	press.button_index = MOUSE_BUTTON_LEFT
	press.pressed = true
	press.position = pos
	press.global_position = pos
	press.set_meta("ball_color", color)
	press.set_meta("ball_radius_px", radius_px)
	if dispatched:
		press.set_meta("ball_dispatched", true)
	Input.parse_input_event(press)

	var release := InputEventMouseButton.new()
	release.button_index = MOUSE_BUTTON_LEFT
	release.pressed = false
	release.position = pos
	release.global_position = pos
	Input.parse_input_event(release)

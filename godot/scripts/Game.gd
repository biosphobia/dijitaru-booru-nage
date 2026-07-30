extends Node2D
## The game: targets pop up on the wall, knock them down with thrown balls
## before the clock runs out. Consecutive hits build a multiplier.
##
## Every screen is navigated by throwing - the title screen's start button
## and the result screen's buttons are ball targets, so a whole session
## needs no keyboard. Everything is sized as a fraction of the projection
## so targets stay throwable at any projector resolution.

const CFG_PATH := "user://game.cfg"
const ROUND_TIME := 60.0
const TARGET_LIFETIME := 3.4
const SPAWN_INTERVAL := 0.85
const MAX_TARGETS := 3
const HIT_SCORE := 10
const MAX_MULTIPLIER := 5

## Target sizes as a fraction of the projection's short side.
const MENU_RADIUS_FRAC := 0.16
const PLAY_RADIUS_FRAC := 0.115

const TARGET_COLOR := Color(1.0, 0.86, 0.35)
const MENU_COLOR := Color(0.98, 0.98, 0.95)
const ACCENT := Color(1.0, 0.86, 0.35)

enum State { TITLE, PLAY, RESULT }

var state := State.TITLE
var score := 0
var combo := 0
var best := 0

var _time_left := 0.0
var _spawn_left := 0.0
var _record := false
var _screen: Node2D = null
var _hud: CanvasLayer
var _score_label: Label
var _time_label: Label
var _combo_label: Label

func _ready() -> void:
	_hud = CanvasLayer.new()
	add_child(_hud)

	_score_label = _make_label(52)
	_score_label.position = Vector2(28, 16)
	_hud.add_child(_score_label)

	_time_label = _make_label(52)
	_time_label.set_anchors_and_offsets_preset(
		Control.PRESET_TOP_RIGHT, Control.PRESET_MODE_MINSIZE, 28)
	_time_label.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	_hud.add_child(_time_label)

	_combo_label = _make_label(38)
	_combo_label.modulate = ACCENT
	_combo_label.set_anchors_and_offsets_preset(
		Control.PRESET_CENTER_TOP, Control.PRESET_MODE_MINSIZE, 22)
	_combo_label.grow_horizontal = Control.GROW_DIRECTION_BOTH
	_hud.add_child(_combo_label)

	_hud.visible = false
	_load_best()
	get_viewport().size_changed.connect(_relayout)
	_show_title()

func _process(delta: float) -> void:
	if state != State.PLAY:
		return
	_time_left -= delta
	if _time_left <= 0.0:
		_time_left = 0.0
		_finish_round()
		return
	_update_hud()
	_spawn_left -= delta
	if _spawn_left <= 0.0 and _live_targets() < MAX_TARGETS:
		_spawn_left = SPAWN_INTERVAL
		_spawn_target()

## Called by Main when the debug mode takes over the screen. The HUD lives
## on its own CanvasLayer, which ignores this node's visibility, so it has
## to be hidden by hand.
func set_active(active: bool) -> void:
	visible = active
	process_mode = Node.PROCESS_MODE_INHERIT if active else Node.PROCESS_MODE_DISABLED
	_hud.visible = active and state == State.PLAY

## Escape / back. Returns false when there is nothing left to back out of.
func on_back() -> bool:
	if state == State.TITLE:
		return false
	_show_title()
	return true

# -- screens ---------------------------------------------------------------

func _show_title() -> void:
	state = State.TITLE
	_hud.visible = false
	_new_screen()
	var vp := get_viewport_rect().size
	var short := minf(vp.x, vp.y)

	_screen_label("デジタルボール投げ", int(short * 0.1), Vector2(vp.x * 0.5, vp.y * 0.15))
	if best > 0:
		_screen_label("ハイスコア %d" % best, int(short * 0.045),
			Vector2(vp.x * 0.5, vp.y * 0.28), ACCENT)

	var start := _target("スタート", Vector2(vp.x * 0.5, vp.y * 0.58),
		short * MENU_RADIUS_FRAC, MENU_COLOR)
	start.hit.connect(_start_round)

	# operator keys, title screen only
	var hint := _screen_label("C: キャリブレーション　D: デバッグ　F: 全画面",
		int(short * 0.03), Vector2(vp.x * 0.5, vp.y * 0.93))
	hint.modulate = Color(1, 1, 1, 0.45)

func _start_round() -> void:
	state = State.PLAY
	score = 0
	combo = 0
	_time_left = ROUND_TIME
	_spawn_left = 0.0
	_new_screen()
	_hud.visible = true
	_update_hud()

func _finish_round() -> void:
	_record = score > best
	if _record:
		best = score
		_save_best()
	_show_result()

func _show_result() -> void:
	state = State.RESULT
	_hud.visible = false
	_new_screen()
	var vp := get_viewport_rect().size
	var short := minf(vp.x, vp.y)

	_screen_label("スコア %d" % score, int(short * 0.1), Vector2(vp.x * 0.5, vp.y * 0.14))
	_screen_label("新記録" if _record else "ハイスコア %d" % best, int(short * 0.05),
		Vector2(vp.x * 0.5, vp.y * 0.27), ACCENT)

	var r := short * MENU_RADIUS_FRAC * 0.9
	var again := _target("もういちど", Vector2(vp.x * 0.3, vp.y * 0.62), r, MENU_COLOR)
	again.hit.connect(_start_round)
	var title := _target("タイトル", Vector2(vp.x * 0.7, vp.y * 0.62), r, MENU_COLOR)
	title.hit.connect(_show_title)

# -- play ------------------------------------------------------------------

func _spawn_target() -> void:
	var r := minf(get_viewport_rect().size.x, get_viewport_rect().size.y) * PLAY_RADIUS_FRAC
	var target := _target("", _free_spot(r), r, TARGET_COLOR, TARGET_LIFETIME)
	target.hit.connect(_on_target_hit)
	target.expired.connect(_on_target_expired)

## Pick a spot whose hit area does not overlap the targets already up -
## overlapping slack would make it ambiguous which target a throw meant.
func _free_spot(r: float) -> Vector2:
	var vp := get_viewport_rect().size
	var short := minf(vp.x, vp.y)
	var margin := r + short * 0.03
	var top := maxf(margin, vp.y * 0.17)
	var fallback := Vector2(vp.x * 0.5, vp.y * 0.55)
	var widest := -INF
	for _i in 16:
		var spot := Vector2(
			randf_range(margin, vp.x - margin),
			randf_range(top, vp.y - margin)
		)
		var gap := INF
		for other in _screen.get_children():
			if other is BallTarget and other.is_ball_active():
				gap = minf(gap, spot.distance_to(other.position)
					- (other.hit_radius() + r + short * 0.05))
		if gap >= 0.0:
			return spot
		if gap > widest:
			widest = gap
			fallback = spot
	return fallback

func _on_target_hit() -> void:
	combo += 1
	score += HIT_SCORE * mini(combo, MAX_MULTIPLIER)
	_update_hud()

func _on_target_expired() -> void:
	combo = 0
	_update_hud()

func _live_targets() -> int:
	var n := 0
	for child in _screen.get_children():
		if child is BallTarget and child.is_ball_active():
			n += 1
	return n

func _update_hud() -> void:
	_score_label.text = "スコア: %d" % score
	_time_label.text = "のこり: %d" % ceili(_time_left)
	_combo_label.text = "×%d" % mini(combo, MAX_MULTIPLIER) if combo > 1 else ""

# -- helpers ---------------------------------------------------------------

func _new_screen() -> void:
	if _screen != null:
		_screen.queue_free()
	_screen = Node2D.new()
	add_child(_screen)

func _target(text: String, pos: Vector2, r: float, color: Color,
		lifetime := 0.0) -> BallTarget:
	var target := BallTarget.new()
	target.position = pos
	target.radius = r
	target.label_text = text
	target.color = color
	target.lifetime = lifetime
	# keep long labels inside the circle
	target.font_size = int(minf(r * 0.34, r * 1.75 / maxf(text.length(), 1.0)))
	_screen.add_child(target)
	return target

func _make_label(size: int) -> Label:
	var label := Label.new()
	label.add_theme_font_size_override("font_size", size)
	return label

## Adds a label to the current screen, centered on `pos`.
func _screen_label(text: String, size: int, pos: Vector2,
		color: Color = Color.WHITE) -> Label:
	var label := _make_label(size)
	label.text = text
	label.modulate = color
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_screen.add_child(label)
	label.reset_size()
	label.position = pos - label.size / 2.0
	return label

func _relayout() -> void:
	match state:
		State.TITLE:
			_show_title()
		State.RESULT:
			_show_result()

func _load_best() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(CFG_PATH) == OK:
		best = int(cfg.get_value("game", "best", 0))

func _save_best() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("game", "best", best)
	cfg.save(CFG_PATH)

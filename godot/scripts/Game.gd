extends Node2D
## Space Booru Nage - the game itself.
##
## You are in the ship. Aliens drift down towards you; a blue ping pong ball
## damages the one it lands nearest, an orange one detonates and clears the
## screen. Survive the wave, take a coin payout, and every few waves pick
## one of two upgrades. Coins are what the stall pays out in sweets, so the
## early waves are gentle and the later ones are not.
##
## Everything a player has to hit is a BallTarget, so a throw only has to
## land close (see BallTarget.hit_radius). Difficulty, payouts and sizes are
## in game.json; art and sound come from game_assets. Neither needs a
## rebuild - see Tuning.gd and GameAssets.gd.
##
## States: TITLE -> INTRO -> PLAY -> (UPGRADE) -> INTRO ... -> RESULT

const CFG_PATH := "user://game.cfg"
## Where the ship is: aliens that get past this line hit the hull.
const SHIP_LINE := 0.86

const COIN_COLOR := Color(1.0, 0.84, 0.3)
const FIRE_COLOR := Color(1.0, 0.55, 0.15)
const BLUE_COLOR := Color(0.45, 0.85, 1.0)

enum State { TITLE, INTRO, PLAY, UPGRADE, RESULT }

## Everything the current run has accumulated. Upgrades write to this.
class Run extends RefCounted:
	var coins := 0
	var wave := 0
	var hull := 5
	var max_hull := 5
	var fireballs := 5
	var damage := 1
	var coin_mult := 1.0
	var slow := 1.0
	var tolerance_bonus := 0.0
	var chain := false
	var turret := 0.0
	var fever := 0
	var revive := false
	var freeze := 0.0
	var hits := 0
	var taken: Array = []

var state := State.TITLE
var run := Run.new()
var best_coins := 0
var best_wave := 0

var _field: Node2D        # aliens, explosions, everything that shakes
var _screen: Node2D       # title / upgrade / result furniture
var _hud: Hud
var _banner: Label = null

var _queue: Array = []
var _spawn_left := 0.0
var _intro_left := 0.0
var _result_left := 0.0
var _freeze_left := 0.0
var _turret_left := 0.0
var _shake := 0.0
var _offered: Array = []
var _cross_time := 24.0
var _spawn_interval := 3.0
var _max_alive := 3
var _wave_escapes := 0
var _last_hit := Vector2.ZERO

func _ready() -> void:
	var stars := Effects.Starfield.new()
	add_child(stars)

	_field = Node2D.new()
	add_child(_field)

	_screen = Node2D.new()
	add_child(_screen)

	var cockpit := Cockpit.new()
	cockpit.z_index = 6
	add_child(cockpit)

	var hud_layer := CanvasLayer.new()
	hud_layer.layer = 2
	add_child(hud_layer)
	_hud = Hud.new()
	hud_layer.add_child(_hud)

	_load_best()
	BallInput.ball_hit.connect(_on_ball_hit)
	get_viewport().size_changed.connect(_relayout)
	Assets.play_music()
	_show_title()

func _process(delta: float) -> void:
	if _shake > 0.0:
		_shake = maxf(0.0, _shake - delta * 26.0)
		_field.position = Vector2(randf_range(-_shake, _shake), randf_range(-_shake, _shake))
	match state:
		State.INTRO:
			_intro_left -= delta
			if _intro_left <= 0.0:
				_begin_wave()
		State.PLAY:
			_play(delta)
		State.RESULT:
			_result_left -= delta
			if _result_left <= 0.0:
				_show_title()

## Main hides the game while the debug mode is up; the HUD is on its own
## CanvasLayer and would otherwise stay on screen.
func set_active(active: bool) -> void:
	visible = active
	process_mode = Node.PROCESS_MODE_INHERIT if active else Node.PROCESS_MODE_DISABLED
	_hud.get_parent().visible = active and state != State.TITLE

## Escape: give up the run, back to the title. False = nothing to leave.
func on_back() -> bool:
	if state == State.TITLE:
		return false
	_show_title()
	return true

func _unhandled_input(event: InputEvent) -> void:
	# reload game.json between customers without closing the game
	if state == State.TITLE and event is InputEventKey and event.pressed \
			and not event.echo and event.keycode == KEY_R:
		Tuning.load_file()
		_show_title()

# -- ball hits -------------------------------------------------------------

## Orange = fireball, anything else = a normal shot. BallInput has already
## worked out which target the throw belongs to and is about to hit it, so
## this only adds what it cannot know: the blast, the miss, the extras.
func _on_ball_hit(pos: Vector2, color: String, _radius_px: float) -> void:
	if state != State.PLAY:
		return
	_last_hit = pos
	# An orange ball only detonates while the player still has one to spend.
	# The camera classifies colour, and a blue ball misread as orange would
	# otherwise hand out free screen clears - and free sweets with them.
	if color == "orange" and run.fireballs > 0:
		_fireball(pos)
		return
	var target := BallInput.pick_target(pos)
	if target == null:
		Assets.play("miss")
		_spark(pos)
		return
	run.hits += 1
	if run.chain and target is Enemy:
		_chain_from(target)
	if run.fever > 0 and run.hits % run.fever == 0:
		_blast(pos, get_viewport_rect().size.x * 0.32, 1)

## The orange ball: one is spent, everything on screen goes up.
func _fireball(pos: Vector2) -> void:
	run.fireballs = maxi(0, run.fireballs - 1)
	Assets.play("fireball")
	_blast(pos, maxf(get_viewport_rect().size.x, get_viewport_rect().size.y) * 1.2,
		int(Tuning.n("fireball.boss_damage", 4)))
	_flash(Color(1.0, 0.6, 0.2, 0.5))
	_shake = 9.0
	_hud.set_run(run)

## Expanding blast front that kills what it reaches. Used by the orange
## ball and, smaller, by the fever upgrade.
func _blast(pos: Vector2, reach: float, boss_damage: int) -> void:
	var wave := Effects.Shockwave.new()
	wave.position = pos
	wave.speed = float(Tuning.n("fireball.wave_speed", 1600.0))
	wave.max_radius = reach
	_field.add_child(wave)
	for enemy in _enemies():
		var distance := enemy.position.distance_to(pos)
		if distance > reach:
			continue
		var delay := distance / maxf(wave.speed, 1.0)
		get_tree().create_timer(delay).timeout.connect(
			func() -> void:
				if is_instance_valid(enemy):
					enemy.blast(boss_damage))

## The chain upgrade: the shot also clips the closest other alien.
func _chain_from(source: Node2D) -> void:
	var best: Enemy = null
	var best_distance := INF
	for enemy in _enemies():
		if enemy == source:
			continue
		var distance := enemy.position.distance_to(source.position)
		if distance < best_distance:
			best_distance = distance
			best = enemy
	if best != null and best_distance < get_viewport_rect().size.x * 0.45:
		var line := Effects.FloatText.new()
		line.text = "連鎖"
		line.color = BLUE_COLOR
		line.font_size = 26
		line.position = best.position
		_field.add_child(line)
		best.take()

# -- waves -----------------------------------------------------------------

func _start_run() -> void:
	run = Run.new()
	run.hull = int(Tuning.n("run.hull", 5))
	run.max_hull = run.hull
	run.fireballs = int(Tuning.n("run.fireballs", 5))
	run.damage = int(Tuning.n("run.damage", 1))
	run.coin_mult = float(Tuning.n("coins.multiplier", 1.0))
	_clear_field()
	_clear_screen()
	_hud.get_parent().visible = true
	Assets.play("start")
	_next_wave()

func _next_wave() -> void:
	run.wave += 1
	var start := float(Tuning.n("waves.cross_time_start", 28.0))
	_cross_time = maxf(float(Tuning.n("waves.cross_time_min", 12.0)),
		start - float(Tuning.n("waves.cross_time_step", 1.4)) * (run.wave - 1))
	_spawn_interval = maxf(float(Tuning.n("waves.spawn_interval_min", 1.1)),
		float(Tuning.n("waves.spawn_interval_start", 3.4))
		- float(Tuning.n("waves.spawn_interval_step", 0.18)) * (run.wave - 1))
	_max_alive = mini(int(Tuning.n("waves.max_alive_max", 6)),
		int(Tuning.n("waves.max_alive_start", 4)) + (run.wave - 1) / 2)
	_queue = _build_wave(run.wave)
	_wave_escapes = 0
	_intro_left = float(Tuning.n("waves.intro_seconds", 2.0))
	state = State.INTRO
	_show_banner("ウェーブ %d" % run.wave)
	Assets.play("wave")
	_hud.set_run(run)

func _begin_wave() -> void:
	state = State.PLAY
	_freeze_left = run.freeze
	_turret_left = run.turret
	_spawn_left = 0.0
	_hide_banner()

func _play(delta: float) -> void:
	if _freeze_left > 0.0:
		_freeze_left -= delta
	if run.turret > 0.0:
		_turret_left -= delta
		if _turret_left <= 0.0:
			_turret_left = run.turret
			_turret_shot()
	_spawn_left -= delta
	if not _queue.is_empty() and _spawn_left <= 0.0 and _enemies().size() < _max_alive:
		_spawn(_queue.pop_front())
		_spawn_left = _spawn_interval
	if _queue.is_empty() and _enemies().is_empty():
		_wave_cleared()

func _wave_cleared() -> void:
	var bonus := int(round(run.wave * float(Tuning.n("coins.wave_clear", 1.0))))
	if _wave_escapes == 0:
		bonus += int(Tuning.n("coins.perfect_wave", 3))
	_award(bonus, get_viewport_rect().size * Vector2(0.5, 0.42))
	var every := maxi(1, int(Tuning.n("run.upgrade_every", 3)))
	if run.wave % every == 0:
		_show_upgrades()
	else:
		_next_wave()

## Pick the wave's aliens out of a points budget, so waves grow in weight
## rather than by a hand-written list, and keep going forever.
func _build_wave(wave: int) -> Array:
	var budget := minf(float(Tuning.n("waves.budget_max", 18.0)),
		float(Tuning.n("waves.budget_base", 3.5))
		+ float(Tuning.n("waves.budget_per_wave", 1.3)) * (wave - 1))
	var boss_every := int(Tuning.n("waves.boss_every", 5))
	var boss := boss_every > 0 and wave % boss_every == 0
	if boss:
		budget *= 0.55

	var choices := []
	for type in Tuning.enemy_types():
		var stats := Tuning.enemy(type)
		if float(stats.get("cost", 0.0)) > 0.0 and int(stats.get("from_wave", 99)) <= wave:
			choices.append({"type": type, "cost": float(stats["cost"]),
				"weight": 1.0 + float(stats.get("from_wave", 1))})
	var list := []
	while list.size() < 16:
		var affordable := choices.filter(func(c): return c["cost"] <= budget)
		if affordable.is_empty():
			break
		var pick: Dictionary = _weighted(affordable)
		list.append(pick["type"])
		budget -= pick["cost"]
	list.shuffle()
	if boss:
		list.push_front("boss")
	return list

func _weighted(entries: Array) -> Dictionary:
	var total := 0.0
	for entry in entries:
		total += float(entry["weight"])
	var roll := randf() * total
	for entry in entries:
		roll -= float(entry["weight"])
		if roll <= 0.0:
			return entry
	return entries[-1]

# -- aliens ----------------------------------------------------------------

func _spawn(type: String, at := Vector2.INF) -> Enemy:
	var vp := get_viewport_rect().size
	var stats := Tuning.enemy(type)
	var r := float(stats.get("radius", 0.13)) * minf(vp.x, vp.y)
	var ship := vp.y * SHIP_LINE
	var enemy := Enemy.new().setup(type, r,
		(ship + r) / _cross_time * float(stats.get("speed", 1.0)) * run.slow)
	enemy.ship_y = ship
	enemy.hit_damage = run.damage
	enemy.tolerance_bonus = run.tolerance_bonus
	enemy.frozen = _freeze_left
	enemy.position = _spawn_point(r) if at == Vector2.INF else at
	enemy.hit.connect(_on_enemy_killed.bind(enemy))
	enemy.damaged.connect(func() -> void: Assets.play("hit"))
	enemy.escaped.connect(_on_enemy_escaped.bind(enemy))
	_field.add_child(enemy)
	return enemy

## Spawn away from the aliens already up, so two hit areas do not sit on
## top of each other while the player is aiming at one of them.
func _spawn_point(r: float) -> Vector2:
	var vp := get_viewport_rect().size
	var margin := r + vp.x * 0.02
	var best := Vector2(randf_range(margin, vp.x - margin), -r)
	var widest := -INF
	for _i in 10:
		var x := randf_range(margin, vp.x - margin)
		var gap := INF
		for enemy in _enemies():
			if enemy.position.y < vp.y * 0.3:
				gap = minf(gap, absf(enemy.position.x - x) - (enemy.radius + r) * 1.3)
		if gap >= 0.0:
			return Vector2(x, -r)
		if gap > widest:
			widest = gap
			best = Vector2(x, -r)
	return best

func _on_enemy_killed(enemy: Enemy) -> void:
	Assets.play("kill")
	var burst := Effects.Explosion.new()
	burst.position = enemy.position
	burst.radius = enemy.radius
	burst.color = enemy.color
	_field.add_child(burst)
	_award(enemy.coin_value, enemy.position)
	if enemy.type == "splitter":
		for side in [-1.0, 1.0]:
			_spawn("mini", enemy.position + Vector2(side * enemy.radius * 0.9, 0.0))
	if enemy.type == "boss":
		_shake = 7.0
		_flash(Color(1.0, 0.8, 0.3, 0.35))

func _on_enemy_escaped(enemy: Enemy) -> void:
	_wave_escapes += 1
	run.hull -= 1
	Assets.play("hull")
	_flash(Color(1.0, 0.15, 0.15, 0.45))
	_shake = 8.0
	var text := Effects.FloatText.new()
	text.text = "装甲 -1"
	text.color = Color(1.0, 0.4, 0.4)
	text.position = Vector2(enemy.position.x, get_viewport_rect().size.y * SHIP_LINE - 40.0)
	_field.add_child(text)
	_hud.set_run(run)
	if run.hull <= 0:
		if run.revive:
			run.revive = false
			run.hull = 2
			_show_banner("緊急シールド")
			get_tree().create_timer(1.6).timeout.connect(_hide_banner)
			_hud.set_run(run)
		else:
			_game_over()

## The auto-turret upgrade: takes out whatever is furthest along.
func _turret_shot() -> void:
	var target: Enemy = null
	for enemy in _enemies():
		if target == null or enemy.position.y > target.position.y:
			target = enemy
	if target == null:
		return
	var vp := get_viewport_rect().size
	var beam := Beam.new()
	beam.from = Vector2(vp.x * 0.5, vp.y * SHIP_LINE)
	beam.to = target.position
	_field.add_child(beam)
	target.blast(3)

## Everything still descending, including aliens not yet down far enough to
## be hit - a wave is not clear until those have come in too.
func _enemies() -> Array[Enemy]:
	var live: Array[Enemy] = []
	for child in _field.get_children():
		if child is Enemy and child.is_alive():
			live.append(child)
	return live

func _clear_field() -> void:
	for child in _field.get_children():
		child.queue_free()

# -- coins, feedback -------------------------------------------------------

func _award(amount: int, at: Vector2) -> void:
	if amount <= 0:
		return
	var coins := int(round(amount * run.coin_mult))
	run.coins += coins
	var text := Effects.FloatText.new()
	text.text = "+%d" % coins
	text.color = COIN_COLOR
	text.position = at
	_field.add_child(text)
	_hud.set_run(run)

func _spark(at: Vector2) -> void:
	var burst := Effects.Explosion.new()
	burst.position = at
	burst.radius = 26.0
	burst.color = Color(0.6, 0.7, 0.9)
	_field.add_child(burst)

func _flash(color: Color) -> void:
	var flash := Effects.Flash.new()
	flash.color = color
	add_child(flash)

# -- screens ---------------------------------------------------------------

func _show_title() -> void:
	state = State.TITLE
	_clear_field()
	_clear_screen()
	_hud.get_parent().visible = false
	var vp := get_viewport_rect().size
	var short := minf(vp.x, vp.y)

	var logo := Assets.texture("title")
	if logo != null:
		var sprite := Sprite2D.new()
		sprite.texture = logo
		sprite.position = Vector2(vp.x * 0.5, vp.y * 0.17)
		sprite.scale = Vector2.ONE * minf(vp.x * 0.7 / logo.get_width(), 1.0)
		_screen.add_child(sprite)
	else:
		_label("スペースボール投げ", int(short * 0.095), Vector2(vp.x * 0.5, vp.y * 0.15))
	if best_coins > 0:
		_label("最高 %d コイン　ウェーブ %d" % [best_coins, best_wave],
			int(short * 0.042), Vector2(vp.x * 0.5, vp.y * 0.28), COIN_COLOR)

	var start := _target("スタート", Vector2(vp.x * 0.5, vp.y * 0.55), short * 0.16)
	start.hit.connect(_start_run)

	# which ball does what - the only thing a new customer has to know
	var legend := Legend.new()
	legend.position = Vector2(vp.x * 0.5, vp.y * 0.83)
	legend.width = short * 0.5
	_screen.add_child(legend)
	_label("青: 通常　オレンジ: ファイア", int(short * 0.038),
		Vector2(vp.x * 0.5, vp.y * 0.89))

func _show_upgrades(reuse := false) -> void:
	state = State.UPGRADE
	_clear_field()
	_clear_screen()
	var vp := get_viewport_rect().size
	var short := minf(vp.x, vp.y)
	if not reuse:
		var choice_index := run.wave / maxi(1, int(Tuning.n("run.upgrade_every", 3)))
		_offered = Upgrades.offer(choice_index, run.taken)

	_label("アップグレード", int(short * 0.075), Vector2(vp.x * 0.5, vp.y * 0.12))
	var r := short * 0.155
	var spots := [vp.x * 0.28, vp.x * 0.72]
	for i in _offered.size():
		var def: Dictionary = _offered[i]
		var target := _target(str(def["name"]), Vector2(spots[i], vp.y * 0.48), r)
		target.color = Color(1.0, 0.92, 0.6) if int(def["tier"]) >= 3 else Color(0.95, 0.97, 1.0)
		target.hit.connect(_take_upgrade.bind(str(def["id"])))
		_label(str(def["desc"]), int(short * 0.04),
			Vector2(spots[i], vp.y * 0.48 + r + short * 0.06))

func _take_upgrade(id: String) -> void:
	Assets.play("upgrade")
	var announce := Upgrades.apply(run, id)
	_hud.set_run(run)
	_clear_screen()
	if announce.is_empty():
		_next_wave()
		return
	# an upgrade the stall has to act on (hand over more orange balls)
	var vp := get_viewport_rect().size
	_label(announce, int(minf(vp.x, vp.y) * 0.09), vp * Vector2(0.5, 0.45), FIRE_COLOR)
	get_tree().create_timer(2.2).timeout.connect(func() -> void:
		_clear_screen()
		_next_wave())

func _game_over() -> void:
	Assets.play("gameover")
	var record := run.coins > best_coins
	best_coins = maxi(best_coins, run.coins)
	best_wave = maxi(best_wave, run.wave)
	_save_best()
	_draw_result(record)
	_result_left = float(Tuning.n("result_seconds", 20.0))

func _draw_result(record: bool) -> void:
	state = State.RESULT
	_clear_field()
	_clear_screen()
	_hud.get_parent().visible = false
	var vp := get_viewport_rect().size
	var short := minf(vp.x, vp.y)
	_label("ゲームオーバー", int(short * 0.07), Vector2(vp.x * 0.5, vp.y * 0.13))
	# the payout line - big, because the stall reads it off the wall
	_label("%d コイン" % run.coins, int(short * 0.16),
		Vector2(vp.x * 0.5, vp.y * 0.34), COIN_COLOR)
	_label("ウェーブ %d 到達%s" % [run.wave, "　新記録" if record else ""],
		int(short * 0.045), Vector2(vp.x * 0.5, vp.y * 0.52))
	var back := _target("タイトル", Vector2(vp.x * 0.5, vp.y * 0.73), short * 0.13)
	back.hit.connect(_show_title)

func _show_banner(text: String) -> void:
	_hide_banner()
	var vp := get_viewport_rect().size
	_banner = _label(text, int(minf(vp.x, vp.y) * 0.1), vp * Vector2(0.5, 0.4))

func _hide_banner() -> void:
	if _banner != null and is_instance_valid(_banner):
		_banner.queue_free()
	_banner = null

func _clear_screen() -> void:
	for child in _screen.get_children():
		child.queue_free()
	_banner = null

func _label(text: String, size: int, at: Vector2, color := Color.WHITE) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_screen.add_child(label)
	label.reset_size()
	label.position = at - label.size / 2.0
	return label

func _target(text: String, at: Vector2, r: float) -> BallTarget:
	var target := BallTarget.new()
	target.position = at
	target.radius = r
	target.label_text = text
	target.font_size = int(minf(r * 0.32, r * 1.7 / maxf(text.length(), 1.0)))
	_screen.add_child(target)
	return target

func _relayout() -> void:
	match state:
		State.TITLE:
			_show_title()
		State.UPGRADE:
			_show_upgrades(true)
		State.RESULT:
			var left := _result_left
			_draw_result(false)
			_result_left = left

# -- records ---------------------------------------------------------------

func _load_best() -> void:
	var cfg := ConfigFile.new()
	if cfg.load(CFG_PATH) == OK:
		best_coins = int(cfg.get_value("game", "best_coins", 0))
		best_wave = int(cfg.get_value("game", "best_wave", 0))

func _save_best() -> void:
	var cfg := ConfigFile.new()
	cfg.set_value("game", "best_coins", best_coins)
	cfg.set_value("game", "best_wave", best_wave)
	cfg.save(CFG_PATH)

# -- furniture -------------------------------------------------------------

## Coins, wave, hull and fireballs. Numbers are Labels (the project font has
## the Japanese glyphs); the icons are drawn.
class Hud extends Node2D:
	var coins := 0
	var wave := 1
	var hull := 5
	var max_hull := 5
	var fireballs := 5
	var _coins_label: Label
	var _wave_label: Label

	func _ready() -> void:
		z_index = 30
		_coins_label = _make(44)
		_wave_label = _make(44)
		get_viewport().size_changed.connect(_layout)
		_layout()

	func _make(size: int) -> Label:
		var label := Label.new()
		label.add_theme_font_size_override("font_size", size)
		add_child(label)
		return label

	func set_run(run: RefCounted) -> void:
		coins = run.coins
		wave = run.wave
		hull = run.hull
		max_hull = run.max_hull
		fireballs = run.fireballs
		_layout()

	func _layout() -> void:
		var vp := get_viewport_rect().size
		var size := int(minf(vp.x, vp.y) * 0.06)
		_coins_label.add_theme_font_size_override("font_size", size)
		_wave_label.add_theme_font_size_override("font_size", size)
		_coins_label.text = "%d" % coins
		_wave_label.text = "ウェーブ %d" % wave
		_coins_label.reset_size()
		_wave_label.reset_size()
		_coins_label.position = Vector2(vp.x * 0.035 + size * 0.9, vp.y * 0.02)
		_wave_label.position = Vector2(vp.x - _wave_label.size.x - vp.x * 0.03, vp.y * 0.02)
		queue_redraw()

	func _draw() -> void:
		var vp := get_viewport_rect().size
		var size := minf(vp.x, vp.y) * 0.06
		# coin
		var coin_at := Vector2(vp.x * 0.035, vp.y * 0.02 + size * 0.55)
		var coin_tex := Assets.texture("coin")
		if coin_tex != null:
			_stamp(coin_tex, coin_at, size * 0.9)
		else:
			draw_circle(coin_at, size * 0.36, COIN_COLOR)
			draw_circle(coin_at, size * 0.26, COIN_COLOR.darkened(0.25))
		# hull, bottom left
		var heart_tex := Assets.texture("heart")
		var r := size * 0.34
		for i in max_hull:
			var at := Vector2(vp.x * 0.04 + i * r * 2.6, vp.y * 0.905)
			var on := i < hull
			if heart_tex != null:
				_stamp(heart_tex, at, r * 2.2, Color(1, 1, 1, 1.0 if on else 0.22))
			else:
				var color := Color(0.35, 0.95, 0.55) if on else Color(0.3, 0.35, 0.4)
				draw_circle(at, r, color)
				draw_arc(at, r, 0.0, TAU, 24, color.darkened(0.4), 3.0)
		# fireballs, bottom right
		for i in fireballs:
			var at := Vector2(vp.x - vp.x * 0.04 - i * r * 2.6, vp.y * 0.905)
			draw_circle(at, r, FIRE_COLOR)
			draw_circle(at + Vector2(-r * 0.25, -r * 0.25), r * 0.3, Color(1, 1, 1, 0.8))

	func _stamp(tex: Texture2D, at: Vector2, side: float, tint := Color.WHITE) -> void:
		draw_texture_rect(tex, Rect2(at - Vector2(side, side) / 2.0, Vector2(side, side)),
			false, tint)

## The band along the bottom that the aliens must not reach.
class Cockpit extends Node2D:
	func _ready() -> void:
		get_viewport().size_changed.connect(queue_redraw)

	func _draw() -> void:
		var vp := get_viewport_rect().size
		var top := vp.y * SHIP_LINE
		var tex := Assets.texture("cockpit")
		if tex != null:
			draw_texture_rect(tex, Rect2(Vector2(0, top), Vector2(vp.x, vp.y - top)), false)
			return
		var height := vp.y - top
		draw_rect(Rect2(Vector2(0, top), Vector2(vp.x, height)), Color(0.06, 0.08, 0.14))
		draw_line(Vector2(0, top), Vector2(vp.x, top), Color(0.35, 0.7, 1.0, 0.8), 4.0)
		# console in the middle, clear of the hull and fireball readouts
		var console := Rect2(vp.x * 0.36, top + height * 0.22, vp.x * 0.28, height * 0.6)
		draw_rect(console, Color(0.10, 0.14, 0.24))
		draw_rect(console, Color(0.3, 0.6, 1.0, 0.35), false, 2.0)
		for i in 5:
			var at := Vector2(console.position.x + console.size.x * (0.14 + 0.18 * i),
				console.position.y + console.size.y * 0.5)
			draw_circle(at, height * 0.075, Color(0.35, 0.75, 1.0, 0.5 + 0.1 * i))

## Title-screen ball key: blue on the left, orange on the right.
class Legend extends Node2D:
	var width := 300.0

	func _draw() -> void:
		var r := width * 0.09
		draw_circle(Vector2(-width * 0.25, 0), r, BLUE_COLOR)
		draw_circle(Vector2(-width * 0.25 - r * 0.3, -r * 0.3), r * 0.3, Color(1, 1, 1, 0.8))
		draw_circle(Vector2(width * 0.25, 0), r, FIRE_COLOR)
		draw_circle(Vector2(width * 0.25 - r * 0.3, -r * 0.3), r * 0.3, Color(1, 1, 1, 0.8))

## Auto-turret beam, a short-lived line from the ship to the alien.
class Beam extends Node2D:
	var from := Vector2.ZERO
	var to := Vector2.ZERO
	var _age := 0.0

	func _ready() -> void:
		z_index = 7

	func _process(delta: float) -> void:
		_age += delta
		if _age > 0.25:
			queue_free()
			return
		queue_redraw()

	func _draw() -> void:
		var fade := 1.0 - _age / 0.25
		draw_line(from, to, Color(0.5, 1.0, 0.8, fade), 10.0 * fade + 2.0)
		draw_line(from, to, Color(1, 1, 1, fade), 3.0)

extends Node
## Every number worth changing on the day, in game.json next to the game.
##
## The file is written with all defaults on first run. Edited values are
## merged over the defaults, so a file holding only the two lines you care
## about is perfectly fine, and a typo can never take a key away.
##
## Reload it without closing the game with R on the title screen.

const FILE_NAME := "game.json"

const DEFAULTS := {
	"run": {
		"hull": 5,               # hits the ship survives
		"fireballs": 5,          # orange balls the player starts with
		"upgrade_every": 3,      # a choice of upgrades every N waves
		"damage": 1,             # damage per blue ball
	},
	"coins": {
		"multiplier": 1.0,       # scale every payout at once
		"wave_clear": 1.0,       # coins per wave number on clear
		"perfect_wave": 3,       # bonus when nothing reached the ship
	},
	"waves": {
		"budget_base": 5.0,      # enemy "points" in wave 1
		"budget_per_wave": 1.8,  # added per wave
		"budget_max": 18.0,
		"cross_time_start": 18.0,  # seconds an enemy takes to reach the ship
		"cross_time_step": 1.6,    # subtracted per wave
		"cross_time_min": 8.0,
		"spawn_interval_start": 1.8,
		"spawn_interval_step": 0.12,
		"spawn_interval_min": 0.8,
		"max_alive_start": 4,
		"max_alive_max": 7,
		"boss_every": 5,         # boss wave every N waves (0 = never)
		"intro_seconds": 2.0,
	},
	"fireball": {
		"boss_damage": 4,        # a boss survives a blast, everything else does not
		"wave_speed": 1600.0,    # px/s the blast front travels
	},
	"aim": {
		"tolerance": 0.06,       # extra hit radius, fraction of screen width
	},
	## radius is a fraction of the screen's short side; speed scales the
	## wave's cross time; cost is what the enemy takes out of the wave
	## budget (0 = never picked at random).
	"enemies": {
		"grunt":    {"hp": 1, "radius": 0.135, "coins": 1, "cost": 1.0, "from_wave": 1, "speed": 1.0},
		"swift":    {"hp": 1, "radius": 0.095, "coins": 2, "cost": 1.6, "from_wave": 3, "speed": 1.9},
		"armor":    {"hp": 3, "radius": 0.150, "coins": 4, "cost": 2.6, "from_wave": 5, "speed": 0.7},
		"splitter": {"hp": 1, "radius": 0.145, "coins": 2, "cost": 2.2, "from_wave": 7, "speed": 0.9},
		"shield":   {"hp": 2, "radius": 0.130, "coins": 3, "cost": 2.6, "from_wave": 9, "speed": 0.85},
		"mini":     {"hp": 1, "radius": 0.080, "coins": 1, "cost": 0.0, "from_wave": 99, "speed": 1.5},
		"boss":     {"hp": 6, "radius": 0.230, "coins": 15, "cost": 0.0, "from_wave": 99, "speed": 0.45},
	},
	"audio": {
		"volume_db": 0.0,
		"music_db": -8.0,
	},
	"result_seconds": 20.0,      # result screen returns to the title after this
}

var data := {}
var path := ""

func _ready() -> void:
	path = _dir().path_join(FILE_NAME)
	load_file()

func load_file() -> void:
	data = DEFAULTS.duplicate(true)
	if not FileAccess.file_exists(path):
		save_defaults()
		return
	var text := FileAccess.get_file_as_string(path)
	var parsed: Variant = JSON.parse_string(text)
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("Tuning: %s is not valid JSON, using defaults" % path)
		return
	_merge(data, parsed)
	print("Tuning: loaded ", path)

func save_defaults() -> void:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file:
		file.store_string(JSON.stringify(DEFAULTS, "\t") + "\n")
		file.close()
		print("Tuning: wrote ", path)

## Value at a dotted path, e.g. n("waves.budget_base").
func n(key_path: String, fallback: Variant = 0.0) -> Variant:
	var node: Variant = data
	for part in key_path.split("."):
		if typeof(node) != TYPE_DICTIONARY or not node.has(part):
			return fallback
		node = node[part]
	return node

## Stats for one enemy type, defaults filled in.
func enemy(type: String) -> Dictionary:
	var base: Dictionary = DEFAULTS["enemies"].get(type, DEFAULTS["enemies"]["grunt"])
	var stats: Dictionary = base.duplicate()
	var edited: Variant = n("enemies." + type, {})
	if typeof(edited) == TYPE_DICTIONARY:
		for key in edited:
			stats[key] = edited[key]
	return stats

func enemy_types() -> Array:
	return DEFAULTS["enemies"].keys()

func _dir() -> String:
	if OS.has_feature("editor"):
		return ProjectSettings.globalize_path("res://").path_join("..").simplify_path()
	return OS.get_executable_path().get_base_dir()

## Edited values win, but only where they exist - missing or misspelled
## keys keep their default instead of disappearing.
func _merge(into: Dictionary, from: Dictionary) -> void:
	for key in from:
		if into.has(key) and typeof(into[key]) == TYPE_DICTIONARY \
				and typeof(from[key]) == TYPE_DICTIONARY:
			_merge(into[key], from[key])
		else:
			into[key] = from[key]

class_name Upgrades
extends Object
## The choice of two that shows up every few waves.
##
## Tiers unlock as the run goes on: the first choice offers small, obvious
## help, later ones offer things that change how the run plays. `tier` is
## the earliest choice number an upgrade can appear at; `repeat` marks the
## ones that stack and may be offered again.
##
## `add` upgrades hand the player more physical orange balls - the game
## announces those loudly so the person running the stall knows to pass
## them over.

const DEFS := [
	# tier 1 - straightforward help
	{"id": "aim", "tier": 1, "repeat": true,
		"name": "照準拡大", "desc": "当たり判定が広がる"},
	{"id": "fire", "tier": 1, "repeat": true, "balls": 2,
		"name": "ファイア +2", "desc": "オレンジ球を2個もらえる"},
	{"id": "repair", "tier": 1, "repeat": true,
		"name": "装甲修復", "desc": "装甲が2回復する"},
	{"id": "coin", "tier": 1, "repeat": true,
		"name": "コイン +30%", "desc": "もらえるコインが増える"},
	# tier 2 - changes how a throw behaves
	{"id": "power", "tier": 2, "repeat": false,
		"name": "二連撃", "desc": "1発の威力が2倍"},
	{"id": "chain", "tier": 2, "repeat": false,
		"name": "連鎖", "desc": "命中した敵の隣にも当たる"},
	{"id": "slow", "tier": 2, "repeat": true,
		"name": "重力網", "desc": "敵の動きが20%遅くなる"},
	{"id": "hull", "tier": 2, "repeat": true,
		"name": "装甲増設", "desc": "装甲の上限が1増える"},
	# tier 3 - run-defining
	{"id": "turret", "tier": 3, "repeat": false,
		"name": "自動砲台", "desc": "12秒ごとに敵を1体撃破"},
	{"id": "fever", "tier": 3, "repeat": false,
		"name": "フィーバー", "desc": "8命中ごとに小爆発"},
	{"id": "revive", "tier": 3, "repeat": false,
		"name": "緊急シールド", "desc": "撃沈を1回だけ耐える"},
	{"id": "freeze", "tier": 3, "repeat": false,
		"name": "時間停止", "desc": "ウェーブ開始時 敵が4秒止まる"},
	{"id": "gold", "tier": 3, "repeat": false,
		"name": "コイン2倍", "desc": "もらえるコインが2倍"},
]

## Two upgrades to choose between. `choice_index` counts from 1 and caps
## which tiers may appear; higher tiers are favoured once unlocked so a
## late choice does not feel like the first one again.
static func offer(choice_index: int, taken: Array) -> Array:
	var pool := []
	for def in DEFS:
		if int(def["tier"]) > choice_index:
			continue
		if not bool(def["repeat"]) and taken.has(def["id"]):
			continue
		# weight: the newest tier available comes up most often
		var weight := 1.0 + 2.0 * float(def["tier"])
		pool.append({"def": def, "key": randf() * weight})
	pool.sort_custom(func(a, b): return a["key"] > b["key"])
	var offered := []
	for entry in pool:
		offered.append(entry["def"])
		if offered.size() == 2:
			break
	return offered

## Apply `id` to the run state. Returns a short line to announce, or "".
static func apply(run: Object, id: String) -> String:
	run.taken.append(id)
	match id:
		"aim":
			run.tolerance_bonus += 0.02
		"fire":
			run.fireballs += 2
			return "オレンジ球 +2"
		"repair":
			run.hull = mini(run.hull + 2, run.max_hull)
		"coin":
			run.coin_mult += 0.3
		"power":
			run.damage = 2
		"chain":
			run.chain = true
		"slow":
			run.slow *= 0.8
		"hull":
			run.max_hull += 1
			run.hull += 1
		"turret":
			run.turret = 12.0
		"fever":
			run.fever = 8
		"revive":
			run.revive = true
		"freeze":
			run.freeze = 4.0
		"gold":
			run.coin_mult *= 2.0
	return ""

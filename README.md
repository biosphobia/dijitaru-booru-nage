# dijitaru-booru-nage

Throw ping pong balls at a wall, hit targets in a projected Godot game.

**スペースボール投げ** — you are inside a spaceship and aliens are drifting
down towards you. A **blue** ball damages the alien it lands nearest; an
**orange** ball is a fireball that detonates and clears the screen. Clear a
wave, collect coins, and every third wave choose one of two upgrades. Coins
are the payout: at a stall they buy sweets.

The whole game is played by throwing — there is nothing to click, not even
to start. Every target has a hit area noticeably larger than the circle you
see (the thin ring around it) to absorb throw and tracking error, and a hit
goes to the target it lands nearest, so a throw only has to be close.

- **Waves** grow from a points budget, so they never run out. New alien
  types unlock as you go: fast little ones, armoured ones that need three
  hits, splitters, shielded ones, and a boss every fifth wave.
- **Hull**: five hits. An alien that reaches the ship costs one; the run
  ends when the hull is gone, and the result screen shows the coin total in
  large type for whoever is paying out.
- **Fireballs**: the player starts with 5 orange balls. Some upgrades hand
  over 2 more — the game announces 「オレンジ球 +2」 full-screen so the
  person running the stall knows to pass them over.
- **Upgrades** every third wave, two to choose between, thrown at like
  anything else. Later choices get stronger: wider hit areas and repairs
  early, then double damage, chain hits and slow fields, then an auto
  turret, a fever blast every eighth hit, a one-shot revive, double coins.

Difficulty, payouts and sizes are all in `game.json`, and every image and
sound can be replaced from a folder — see **Setting up the game** below.
Neither needs a rebuild.

### Debug mode (press **D**)

The two development modes live behind **D**, out of the way of players:

- **Ball Game** (「ボール」) — the ball popup test game (throw a ball, pop
  the target). Useful for checking tracking accuracy.
- **Model Studio** (「スタジオ」) — photograph a person from up to 4 angles
  with the tracking camera and turn them into a **rigged 3D model** via
  [Meshy.ai](https://www.meshy.ai), with live progress and a rotating 3D
  preview in-game. Models are stored in your Meshy cloud account, so they
  survive the game being closed; the newest one is also cached locally.

The debug menu is throwable as well (「もどる」 leaves it); **D** also backs
out of a running debug mode, and **1** / **2** pick one from the keyboard.

A webcam watches the projected image. A Python script detects ball impacts
(a fast round blob whose direction suddenly reverses = a bounce off the
wall), converts the impact point to game coordinates with a homography, and
sends it to the game over UDP. The game turns each hit into a normal left
mouse click, so any click-based game just works.

```
webcam -> vision/detect.py -> UDP {"type":"hit","x":0.42,"y":0.61,"color":"red"}
                                -> Godot BallInput autoload -> mouse click + ball_hit signal
```

## Parts

- `godot/` — Godot 4.5 project. The game is `Game.gd` (waves, coins, hull,
  screens) with `Enemy.gd`, `Upgrades.gd` and `Effects.gd`; `BallTarget.gd`
  is the throwable target everything else is built from. `GameAssets.gd`
  and `Tuning.gd` are the autoloads that read `game_assets/` and
  `game.json`. `BallInput.gd` receives hits from the camera tool,
  `DebugMenu.gd` holds the development modes, and `CalibrationScreen.gd`
  draws the calibration pattern.
- `vision/` — Python: `calibrate.py` (homography calibration),
  `detect.py` (ball tracker), `test_hit.py` (send a fake hit, no camera needed).

## Download everything (zero install)

Grab the newest builds from the [Releases page](../../releases) — every
push to `main` refreshes the **Latest build** pre-release. Nothing needs
to be installed on the PC, not even Python: download, unzip, run.

- **Game**: `DijitaruBooruNage-windows.zip` — unzip anywhere,
  double-click the `.exe`. Put it on the PC driving the projector.
- **Camera tool**: `BooruVision-windows.zip` — a single portable
  executable with calibrate/detect built in. Unzip, double-click
  `BooruVision.exe`, pick from the menu (1 = calibrate, 2 = detect). If
  SmartScreen complains: "More info" > "Run anyway".

Builds are currently Windows-only (macOS is on hold; presets remain in
the repo).

`config.json` (tuning) and `calibration.json` are created **next to the
executable** on first run, so the whole thing lives in one folder — a USB
stick works fine.

## Using a PS3 Eye camera (Windows)

The PS3 Eye is a great tracking camera — cheap and it does a true
**60 fps at 640x480**, which is exactly what the defaults in
`config.json` are tuned for. It is *not* a standard webcam though, so
Windows needs a one-time driver install (the only install the whole
project needs). Either driver works — the tool captures via DirectShow:

- **CL-Eye Platform Driver** (Code Laboratories): the classic driver.
  Install it, plug in the camera, and check it works in the bundled
  CL-Eye Test app first — if that shows 60 fps video, `BooruVision.exe`
  will too. Unmaintained, so if a Windows update breaks it, switch to:
- **[PS3EyeDirectShow](https://github.com/jkevin/PS3EyeDirectShow/releases)**
  (or the [AllanCat fork](https://github.com/AllanCat/PS3EyeDirectShow)):
  open-source WinUSB driver + DirectShow filter.

If another camera is also connected and the wrong one opens, change
`camera_index` in `config.json` (0, 1, 2...).

Note: the in-game Model Studio viewfinder uses Media Foundation, which
may not see the PS3 Eye through these DirectShow drivers — the viewfinder
then falls back to streaming from the camera tool automatically. Ball
tracking is unaffected either way.

Using a **regular webcam** instead: set `capture_width`/`capture_height`
to `1280`/`720` and `fourcc` to `"MJPG"` in `config.json` so it can reach
60 fps.

## Setup from source (for developing)

1. Install [Godot 4.5+](https://godotengine.org) and Python 3.9+.
   The Model Studio viewfinder uses the machine's camera directly through
   Godot: built-in on macOS; on Windows/Linux the release builds bundle
   [CameraServerExtension](https://github.com/j20001970/godot-cameraserver-extension)
   (for editor runs on those platforms, drop its `addons/` folder into
   `godot/` — it is fetched by CI and not committed).
2. `pip install -r vision/requirements.txt`
3. Open `godot/project.godot` in Godot and run it (F5). The Python
   entry points are `vision/calibrate.py` and `vision/detect.py` (or
   `vision/app.py` for the menu).

## Physical setup

1. Run the game on the projector and press **F** for fullscreen.
2. Place the webcam so it sees the **whole projected image** (next to the
   projector is easiest). Fix it in place — if the camera or projector
   moves, recalibrate.
3. macOS only: the first time you run a vision script, macOS asks for
   Camera permission for your terminal app — allow it (System Settings >
   Privacy & Security > Camera).

## Calibrate (do this once per setup)

1. In the running game, press **C** — the screen turns white with a 4x3
   grid of square markers.
2. Run `python vision/calibrate.py`. A camera preview opens and collects
   marker observations over time — markers only need to be spotted now
   and then, not in every frame. Green dots mark locked markers; the
   border turns green once enough are locked (6 of 12 suffice, more =
   more accurate).
3. Press **SPACE** to save (`vision/calibration.json`), **R** to restart
   collecting, then press **C** in the game to return.

The fit combines a perspective homography with a spline correction
measured at each marker, so it stays accurate from low camera angles and
on keystoned or slightly curved screens. If you move the camera or
projector even a little, recalibrate — it only takes a few seconds.

## Play

```
python vision/detect.py
```

Throw a ball at the wall. A hit only registers on **contact** — the
tracker watches for the ball's trajectory to break sharply (the bounce);
a ball merely flying across the projection does nothing. Each impact
prints `HIT {...}` in the terminal and clicks the game at that spot: a
mark in the ball's color (light blue / orange) and at the ball's real
projected size appears there and fades out, so you can compare it
against where the ball actually struck — the mark always shows the raw
impact point, even when the hit was awarded to a target next to it.

No camera handy? Test the game side alone:

```
python vision/test_hit.py 0.5 0.5 orange
```

The ball's **colour decides what the throw does**: `lightblue` is a normal
shot, `orange` is a fireball. That comes from the `colors` ranges in
`vision/config.json`, so tune those in the room's actual light before
opening — a blue ball read as orange spends a fireball.

## Setting up the game

Two things sit **next to the game executable** and belong to whoever runs
the stall. Both are created on first run, and neither needs Godot or a
rebuild.

### `game_assets/` — art and sound

Drop a file in, restart the game, done. Everything is optional: whatever is
missing keeps the built-in look, so an empty folder is a working game.

```
game_assets/
  images/   background, cockpit, title, enemy_grunt, enemy_swift,
            enemy_armor, enemy_splitter, enemy_shield, enemy_mini,
            enemy_boss, explosion, fireball, coin, heart, target
  sounds/   start, wave, hit, kill, miss, fireball, hull, upgrade,
            gameover, music
```

Images are `.png` / `.jpg` / `.webp`, drawn centred on the thing they
replace and scaled to its size — square with a transparent background
works best. Sounds are `.ogg` / `.wav` / `.mp3`; `music` loops for the
whole session. The folder's `README.txt` lists every name with what it is
used for. (The aliens' Meshy models will plug in at the same spot later,
rendered to a texture instead of a file.)

### `game.json` — difficulty and payouts

Written with every default the first time the game runs. Edited values are
merged over the defaults, so a file holding only the two lines you care
about is fine, and a typo can never delete a setting. Press **R** on the
title screen to reload it without closing the game — that is the knob to
turn between customers.

The ones worth knowing on the day:

| key | what it does |
| --- | --- |
| `run.hull` | hits the ship survives (5) |
| `run.fireballs` | orange balls the player starts with (5) |
| `run.upgrade_every` | a choice of upgrades every N waves (3) |
| `coins.multiplier` | scales every payout at once — the prize dial |
| `waves.budget_base` / `budget_per_wave` | how many aliens wave 1 has, and how fast that grows |
| `waves.cross_time_start` / `_step` / `_min` | seconds an alien takes to reach the ship, and how much faster each wave gets |
| `waves.max_alive_start` / `_max` | how many can be on screen at once |
| `waves.boss_every` | boss wave every N waves (0 = never) |
| `aim.tolerance` | throw slack, as a fraction of screen width (0.06 ≈ 77 px at 1280) — raise it if the room is unforgiving |
| `enemies.<type>` | per-alien hp, radius, coins, speed, and which wave it first appears in |

**Too hard for the queue?** Raise `run.hull`, raise `aim.tolerance`, raise
`waves.cross_time_start`. **Paying out too much candy?** Lower
`coins.multiplier` — it scales kills and bonuses together.

### What a run looks like

Measured against a simulated player throwing every 2.4 s with realistic aim
error, on the shipped defaults:

| wave | 1–5 | 6 | 7 | 8 |
| --- | --- | --- | --- | --- |
| hull left (of 5) | 5 | 3 | 2 | 2 |
| coins | 49 | 79 | 118 | 118+ |

So: nothing gets through for the first five waves, the pressure starts at
wave 6, and a run ends around wave 9 — about 3½ minutes, ~130 coins. A
first-timer throwing more slowly will end around wave 5–6 with 40–60.
Pick the prize exchange rate from that, and use `coins.multiplier` to move
every payout at once rather than editing each alien.

## Model Studio (Meshy.ai)

One-time setup: get an API key from
[Meshy API settings](https://www.meshy.ai/settings/api) and put it in
`config.json` next to the camera tool:

```json
"meshy": { "api_key": "msy-...", "ai_model": "latest", "rig": true, "height_meters": 1.7 }
```

Then, with the camera tool running (`detect`), press **D** and pick
**スタジオ**:

1. A live camera viewfinder shows in the game. Stand in front of the
   camera and click 「撮影」 for 1–4 angles (front / side / back work
   best), or add existing image files with 「ファイル追加」. Photos are
   also saved to `photos/` next to the tool.
2. Edit the **texture prompt** in the game at any time (saved between
   sessions).
3. Click **Generate 3D model** — the progress bar tracks Meshy in real
   time (model build, then automatic rigging; rigging needs a clear
   humanoid pose and falls back to the unrigged model if it fails).
4. The finished model appears rotating in the 3D view. It lives in your
   Meshy account (**Load newest from Meshy cloud** re-fetches it any
   time) and is cached locally so it reappears after a restart.

Costs credits per generation on your Meshy account. The whole Meshy
conversation runs through the camera tool, so the game itself never
needs the API key.

## Tuning (`vision/config.json`)

- `detection.mode`:
  - `"reversal"` (default) — fires when a tracked ball bounces off the
    wall. Use this for real play.
  - `"instant"` — fires on the first fast motion it sees. Handy for desk
    testing by waving a ball in front of the camera.
- `screen_height_m` — the **measured physical height of the projected
  image in meters**. The single most useful measurement: it drives the
  gravity correction of hit positions and (with `ball_diameter_m`,
  default 0.04 for a standard ping pong ball) the expected ball blob
  size at every camera distance. Measure it once the setup is final.
- `auto_scale` (default on) — derives all pixel-space tracker constants
  (blob area bounds, track match radius) from the calibration's local
  image scale, so any reasonable camera distance and angle works
  without retuning. Camera distance/angle themselves never need to be
  entered — the calibration grid captures them. **Re-run calibrate.py
  whenever the camera or projector moves**, including after final
  setup.
- `min_area` / `max_area` — accepted blob size in pixels (at the 640-wide
  processing scale); only used as fallback when `auto_scale` is off or
  no calibration exists. A fast ball is a motion-blur *streak*, so blobs
  are elongated — that is expected and handled.
- `auto_threshold` / `noise_multiplier` — the motion threshold floats
  above the measured sensor grain automatically (essential for the PS3
  Eye). Raise `noise_multiplier` if grain still becomes blobs;
  `diff_threshold` is the fixed floor.
- `min_speed_norm` — minimum ball speed in screen units per frame
  (1.0 = screen height; 0.012 at 60 fps is ~1.2 m/s). Lower it if soft
  throws are missed.
- `screen_aspect` — physical width/height of the projection (default
  16:9). All contact physics runs in calibrated screen space, so camera
  angle and perspective do not affect the thresholds.
- `approach_frames` — a hit needs up to this many consecutive fast,
  straight, similar-speed steps before the bounce (default 4; shorter
  clean windows are accepted when early observations are noisy). This
  is the main noise gate: grain and light artifacts cannot fake a real
  approach.
- `straightness_deg` — how much the approach may wobble (default 45°).
- `min_turn_deg` — how sharply the trajectory must break at contact
  (default 60°). Raise toward 90 if passing balls false-trigger; lower
  toward 45 if soft contacts are missed.
- `cooldown_ms` / `cooldown_radius` — double-hit suppression (a ball
  bouncing twice near the same spot counts once).
- In the detect preview window, press **M** to see the motion mask —
  if it is full of speckles, raise `noise_multiplier`; if the ball
  streak is invisible in it, lower `diff_threshold`.
- `colors` — HSV ranges used to name the ball color (`h` 0–179, OpenCV
  convention). Ships with `lightblue` and `orange`. Tune them in your
  actual room lighting: the projector tints the balls.

## Practical tips

- Use a camera mode with **60 fps** if available — a ping pong ball is fast,
  and the tracker needs a few frames near the wall to see the bounce.
- Keep some room light on. The tracker uses motion, not color, to *detect*
  balls, but color *classification* needs the ball to be lit by something
  other than the projection.
- Matte balls beat glossy ones (less projector glare).
- Balls are only reported inside the projected area; throws that miss the
  screen are ignored.

## Making your own game

Build it in `godot/` against plain mouse clicks — targets, buttons,
`_unhandled_input`, whatever. Ball hits arrive as real clicks. For anything
a player has to hit, use `BallTarget` instead of a `Button`: it is a round
target with built-in throw slack (`TOLERANCE_FRAC`, ~6% of screen width on
top of its radius), and hits are routed to the nearest one:

```gdscript
var target := BallTarget.new()
target.position = Vector2(640, 400)
target.radius = 110.0
target.label_text = "スタート"
target.hit.connect(func() -> void: print("hit!"))
add_child(target)
```

If you want the ball color (team play!), connect to the autoload's signal
instead:

```gdscript
BallInput.ball_hit.connect(func(pos: Vector2, color: String, radius_px: float):
    print("ball hit at ", pos, " color ", color, " size ", radius_px))
```

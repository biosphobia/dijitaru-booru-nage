# dijitaru-booru-nage

Throw ping pong balls at a wall, hit targets in a projected Godot game.

The game is played entirely by throwing — there is nothing to click. It
opens on a title screen whose **スタート** target starts a 60 second round:
targets pop up on the wall, each hit scores, consecutive hits build a
multiplier, and the result screen offers **もういちど** / **タイトル** as
targets too. The high score is kept between sessions.

Every target has a hit area noticeably larger than the circle you see (the
faint halo around it) to absorb throw and tracking error, and a hit is
awarded to the target it lands nearest — so a throw only has to be close.

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

- `godot/` — Godot 4.5 project: the game (`Game.gd`), the debug mode
  (`DebugMenu.gd` + `BallGame.gd` / `ModelStudio.gd`), the throwable target
  (`BallTarget.gd`), the calibration pattern screen, and the `BallInput.gd`
  autoload that receives hits.
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
- `min_area` / `max_area` — accepted blob size in pixels (at the 640-wide
  processing scale). A fast ball is a motion-blur *streak*, so blobs are
  elongated — that is expected and handled.
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

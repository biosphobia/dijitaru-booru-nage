# dijitaru-booru-nage

Throw ping pong balls at a wall, hit targets in a projected Godot game.

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

- `godot/` — Godot 4.3 project: the test game (a white ball appears at a
  random point on a blue background; a hit pops it and a new one appears),
  the calibration pattern screen, and the `BallInput.gd` autoload that
  receives hits.
- `vision/` — Python: `calibrate.py` (homography calibration),
  `detect.py` (ball tracker), `test_hit.py` (send a fake hit, no camera needed).

## Download everything (zero install)

Grab the newest builds from the [Releases page](../../releases) — every
push to `main` refreshes the **Latest build** pre-release. Nothing needs
to be installed on the PC, not even Python: download, unzip, run.

**The game** (put on the PC driving the projector):

- **Windows**: `DijitaruBooruNage-windows.zip` — unzip anywhere,
  double-click the `.exe`.
- **macOS**: `DijitaruBooruNage-macos.zip` — unzip, then
  **right-click the app > Open** the first time (the app is unsigned, so
  a normal double-click is blocked by Gatekeeper once). If macOS still
  refuses: `xattr -cr "Dijitaru Booru Nage.app"` in a terminal.

**The camera tool** (same PC, the one the webcam is plugged into) — a
single portable executable with calibrate/detect built in:

- **Windows**: `BooruVision-windows.zip` — unzip, double-click
  `BooruVision.exe`, pick from the menu (1 = calibrate, 2 = detect). If
  SmartScreen complains: "More info" > "Run anyway".
- **macOS**: `BooruVision-macos-applesilicon.zip` (M1/M2/M3/M4) or
  `BooruVision-macos-intel.zip` (older Intel Macs) — unzip, run
  `xattr -cr BooruVision` in Terminal once, then double-click it.

`config.json` (tuning) and `calibration.json` are created **next to the
executable** on first run, so the whole thing lives in one folder — a USB
stick works fine.

## Setup from source (for developing)

1. Install [Godot 4.3+](https://godotengine.org) and Python 3.9+.
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

1. In the running game, press **C** — the screen turns white with four
   square markers.
2. Run `python vision/calibrate.py`. A camera preview opens; when all four
   markers are detected the border turns green.
3. Press **SPACE** to save (`vision/calibration.json`), then press **C** in
   the game to return.

## Play

```
python vision/detect.py
```

Throw a ball at the wall. Each detected impact prints `HIT {...}` in the
terminal and clicks the game at that spot: a small ripple shows where the
hit landed, and if it hit the ball, the ball pops and a new one appears.

No camera handy? Test the game side alone:

```
python vision/test_hit.py 0.5 0.5 red
```

## Tuning (`vision/config.json`)

- `detection.mode`:
  - `"reversal"` (default) — fires when a tracked ball bounces off the
    wall. Use this for real play.
  - `"instant"` — fires on the first fast motion it sees. Handy for desk
    testing by waving a ball in front of the camera.
- `min_area` / `max_area` — accepted blob size in pixels (at the 640-wide
  processing scale). Shrink/grow if balls are missed or noise triggers.
- `diff_threshold` — raise if projector flicker causes false motion.
- `min_speed` — minimum ball speed in px/frame; lower it if soft throws
  are missed.
- `cooldown_ms` / `cooldown_radius` — double-hit suppression (a ball
  bouncing twice near the same spot counts once).
- `colors` — HSV ranges used to name the ball color (`h` 0–179, OpenCV
  convention; `red` wraps around). Tune them in your actual room lighting:
  the projector tints the balls.

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
`_unhandled_input`, whatever. Ball hits arrive as real clicks. If you want
the ball color (team play!), connect to the autoload's signal instead:

```gdscript
BallInput.ball_hit.connect(func(pos: Vector2, color: String):
    print("ball hit at ", pos, " color ", color))
```

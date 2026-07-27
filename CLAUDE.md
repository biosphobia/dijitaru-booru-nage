# Project conventions

- **All user-facing in-game text is Japanese.** No English may appear in the
  Godot UI (labels, buttons, status lines, hints). Status/error text coming
  from the Python vision tool is sent as structured events with `stage` /
  `code` fields; the game maps them to Japanese strings — never display raw
  English messages except as a last-resort error detail.
- **Keep UI text minimal.** No instructional or decorative fluff — short
  labels only (e.g. 「撮影」, 「スコア: 3」, 「待機中」).
- The Japanese font is `godot/assets/fonts/NotoSansJP-Regular.ttf`, set as
  the project-wide theme font in `project.godot` (`gui/theme/custom_font`).
  Godot's built-in font has no CJK glyphs — do not remove this setting.
- Python console output and code comments stay English. The OpenCV preview
  windows (calibrate/detect) stay English too — cv2 cannot render Japanese.
- Keep the UI simple overall; the game runs projected on a wall and is
  "clicked" by thrown ping pong balls (see README).

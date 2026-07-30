extends Node
## Hand-editable art and sound, loaded at run time from a folder next to the
## game. Drop in a PNG or an OGG and it replaces what the game draws or
## plays - no rebuild, no Godot, no restart of anything but the game.
##
##   game_assets/images/<name>.png | .jpg | .webp
##   game_assets/sounds/<name>.ogg | .wav | .mp3
##
## Every file is optional: a missing image falls back to the built-in
## procedural art, a missing sound to silence. The folder and a README
## listing every name the game looks for are created on first run.

const IMAGE_EXTS := ["png", "jpg", "jpeg", "webp"]
const SOUND_EXTS := ["ogg", "wav", "mp3"]
const VOICES := 10

## name -> what it is used for (also written into the folder's README).
const IMAGES := {
	"background": "full-screen space background",
	"cockpit": "cockpit frame, drawn across the bottom of the screen",
	"title": "title logo, replaces the title text",
	"enemy_grunt": "basic alien",
	"enemy_swift": "fast little alien",
	"enemy_armor": "armored alien",
	"enemy_splitter": "alien that splits in two",
	"enemy_shield": "shielded alien",
	"enemy_mini": "the small ones a splitter leaves behind",
	"enemy_boss": "boss alien",
	"explosion": "explosion burst",
	"fireball": "fireball shockwave ring",
	"coin": "coin icon in the HUD",
	"heart": "hull icon in the HUD",
	"target": "the plain round target (start button, upgrades)",
}
const SOUNDS := {
	"start": "a round begins",
	"wave": "a wave begins",
	"hit": "enemy damaged but still alive",
	"kill": "enemy destroyed",
	"miss": "ball hit nothing",
	"fireball": "orange ball, screen-clearing blast",
	"hull": "an alien reached the ship",
	"upgrade": "upgrade chosen",
	"gameover": "run over",
	"music": "background music, loops for the whole session",
}

var dir_path := ""

var _tex := {}
var _snd := {}
var _voices: Array[AudioStreamPlayer] = []
var _next_voice := 0
var _music: AudioStreamPlayer

func _ready() -> void:
	dir_path = _external_dir()
	_ensure_folder()
	print("GameAssets: custom art and sound folder: ", dir_path)
	for i in VOICES:
		var player := AudioStreamPlayer.new()
		add_child(player)
		_voices.append(player)
	_music = AudioStreamPlayer.new()
	_music.finished.connect(func() -> void: _music.play())
	add_child(_music)

## Texture for `name`, or null when the user has not supplied one (the
## caller then draws its own).
func texture(name: String) -> Texture2D:
	if _tex.has(name):
		return _tex[name]
	var tex: Texture2D = null
	var path := _find(dir_path.path_join("images"), name, IMAGE_EXTS)
	if not path.is_empty():
		var img := Image.load_from_file(path)
		if img != null and not img.is_empty():
			tex = ImageTexture.create_from_image(img)
		else:
			push_warning("GameAssets: could not read image %s" % path)
	_tex[name] = tex
	return tex

func has_texture(name: String) -> bool:
	return texture(name) != null

## Play a one-shot sound; does nothing when the file is absent.
func play(name: String, pitch := 1.0) -> void:
	var stream := _stream(name)
	if stream == null:
		return
	var player := _voices[_next_voice]
	_next_voice = (_next_voice + 1) % VOICES
	player.stream = stream
	player.pitch_scale = pitch
	player.volume_db = float(Tuning.n("audio.volume_db", 0.0))
	player.play()

func play_music(name := "music") -> void:
	var stream := _stream(name)
	if stream == null or (_music.playing and _music.stream == stream):
		return
	_music.stream = stream
	_music.volume_db = float(Tuning.n("audio.music_db", -8.0))
	_music.play()

func stop_music() -> void:
	_music.stop()

# -- loading ---------------------------------------------------------------

func _stream(name: String) -> AudioStream:
	if _snd.has(name):
		return _snd[name]
	var stream: AudioStream = null
	var path := _find(dir_path.path_join("sounds"), name, SOUND_EXTS)
	if not path.is_empty():
		match path.get_extension().to_lower():
			"ogg":
				stream = AudioStreamOggVorbis.load_from_file(path)
			"mp3":
				stream = AudioStreamMP3.load_from_file(path)
			"wav":
				stream = AudioStreamWAV.load_from_file(path)
		if stream == null:
			push_warning("GameAssets: could not read sound %s" % path)
	_snd[name] = stream
	return stream

func _find(folder: String, name: String, exts: Array) -> String:
	for ext in exts:
		var path := folder.path_join("%s.%s" % [name, ext])
		if FileAccess.file_exists(path):
			return path
	return ""

## Next to the executable in an exported game; next to the repo in the
## editor, so testing does not need an export.
func _external_dir() -> String:
	if OS.has_feature("editor"):
		return ProjectSettings.globalize_path("res://").path_join("../game_assets").simplify_path()
	return OS.get_executable_path().get_base_dir().path_join("game_assets")

func _ensure_folder() -> void:
	DirAccess.make_dir_recursive_absolute(dir_path.path_join("images"))
	DirAccess.make_dir_recursive_absolute(dir_path.path_join("sounds"))
	var readme := dir_path.path_join("README.txt")
	if FileAccess.file_exists(readme):
		return
	var lines := PackedStringArray([
		"Custom art and sound for Dijitaru Booru Nage.",
		"",
		"Drop files in here and restart the game - nothing else to do.",
		"Every file is optional; whatever is missing keeps the built-in look.",
		"",
		"images/  (%s)" % ", ".join(IMAGE_EXTS),
		"  Drawn centred on the thing they replace and scaled to its size,",
		"  so square images with a transparent background work best.",
		"",
	])
	for name in IMAGES:
		lines.append("  %-18s %s" % [name + ".png", IMAGES[name]])
	lines.append("")
	lines.append("sounds/  (%s)" % ", ".join(SOUND_EXTS))
	lines.append("")
	for name in SOUNDS:
		lines.append("  %-18s %s" % [name + ".ogg", SOUNDS[name]])
	lines.append("")
	lines.append("Difficulty, prices and sizes live in game.json next to the game.")
	var file := FileAccess.open(readme, FileAccess.WRITE)
	if file:
		file.store_string("\n".join(lines) + "\n")
		file.close()

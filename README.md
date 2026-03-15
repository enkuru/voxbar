# Voxbar

macOS menu bar app for hands-free voice dictation via [Wispr](https://wispr.com). Double-tap the Fn key to start dictating, tap again to send.

## Features

- **Fn double-tap hotkey** — start/stop dictation without touching the mouse
- **Push-to-talk** — hold Fn after double-tap for PTT mode
- **Auto-enter** — automatically presses Enter after dictation completes
- **Menu bar timer** — animated waveform icon with elapsed time during calls
- **Focus restoration** — returns you to the app you were using before the call
- **Escape to cancel** — press Esc during dictation to cancel without sending
- **Launch at login** — toggle in settings popover

## Requirements

- macOS 12+ (tested on Sequoia)
- Python 3.12+
- [cliclick](https://github.com/BlueM/cliclick) (`brew install cliclick`)
- [Wispr](https://wispr.com) for voice dictation
- iTerm2 (default target terminal — configurable)

## Install

```bash
brew install cliclick
git clone https://github.com/enkuru/voxbar.git
cd voxbar
./install.sh
```

## Uninstall

```bash
cd voxbar
./uninstall.sh
```

## Permissions

Voxbar needs these macOS permissions (System Settings → Privacy & Security):

- **Accessibility** — add both `python3` (at `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`) and `cliclick` for the Fn hotkey and key simulation
- **Automation → iTerm2** — for reading terminal content and sending Enter

## Configuration

Edit `config.json` (created on first run from `config.example.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `target_app` | `"iTerm2"` | Terminal app to target |
| `auto_enter` | `true` | Press Enter after dictation |
| `fn_hotkey_enabled` | `true` | Enable Fn double-tap |
| `double_tap_ms` | `400` | Double-tap speed threshold (ms) |
| `sounds_enabled` | `true` | Play sound effects |

## Usage

- **Fn Fn** — start a call (double-tap)
- **Fn** — hang up (single tap during call)
- **Fn (hold)** — push-to-talk mode (release to hang up)
- **Esc** — cancel call without sending
- **Click menu bar icon** — open settings/start call via UI

## License

MIT

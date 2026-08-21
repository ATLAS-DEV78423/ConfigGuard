# Configuration

`~/.config/rice/config.toml` — created by `rice init`, editable by hand.

```toml
[rice]
data_dir = "/home/you/.local/share/rice"
version = "0.1.0"

[protected]
hyprland = ["/home/you/.config/hypr"]
waybar   = ["/home/you/.config/waybar"]
kitty    = ["/home/you/.config/kitty"]
wofi     = ["/home/you/.config/wofi", "/home/you/.config/rofi"]
extra    = ["/home/you/.config/user-paths"]
```

## Rules

- Paths may be absolute or `~/...`; rice canonicalizes them.
- Keys are app names; values are lists of roots to protect recursively.
- `extra` holds user-selected additional paths.
- A path must live inside your home; anything else is refused.
- Missing config => most commands exit code 3 telling you to run `rice init`.

## Data location

Snapshots, journals, logs, and the lock file live under `data_dir`
(default `~/.local/share/rice/`). Move it by editing `[rice] data_dir`.

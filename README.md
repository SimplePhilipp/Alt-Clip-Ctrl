# Alt Clip Ctrl

A small Windows helper for Clip Studio Paint with configurable keyboard tap/hold gestures, dial tool cycling, and automatic shortcut tracking. No AutoHotkey, installer, network connection, or external packages are needed. Runs on Windows with .NET Framework 4.x.

## Start

1. Exit any older helper using its tray menu **Exit** command.
2. Download the Windows ZIP from [Releases](https://github.com/SimplePhilipp/Alt-Clip-Ctrl/releases/latest), extract it to a writable folder and run **AltClipCtrl.exe**.
3. Click **Config** to change bindings, enable switches, timing, or tool shortcuts. Click **Save** to apply and remember changes.
4. Minimize the window to keep the helper running. Closing the main window exits the application and removes its tray icon. **Pause** in the tray menu temporarily disables the helper.

The window, tray, and executable use the custom pen-and-cycle icon.

## Tap / hold notation

| Notation | Meaning | Default example |
|---|---|---|
| `-` | Tap: press and release quickly | `-Alt` sends B |
| `_` | Hold: keep the key pressed | `_Alt` remains normal Alt |
| `-_` | Tap, release, then press and hold again | `-_Alt` enables dial tool cycling |
| `+` | Press keys together | `_Alt + ]` sends F |

Alt, Ctrl, and Shift have the **same gesture logic**, with independent settings. For example, `-Ctrl` is a quick Ctrl tap, `_Shift` is a normal Shift hold, and `-_Ctrl` is a Ctrl tap followed by a held second press.

By default, each modifier profile is enabled and uses:

| Gesture | Default result |
|---|---|
| `-Alt`, `-Ctrl`, or `-Shift` | B after about 100 ms |
| `_Alt`, `_Ctrl`, or `_Shift` alone | Original modifier, unchanged |
| Ordinary held modifier + `]` | F |
| Ordinary held modifier + `[` | S |
| `-_Alt`, `-_Ctrl`, or `-_Shift` | Tool cycling while the second press stays held |
| In cycling mode: `]` / `[` | Next / previous configured tool |

Use one modifier at a time for these gestures. Native combinations such as Ctrl+C, Ctrl+Shift+C, Alt+Tab, and Shift+click retain their ordinary behavior. Modifier use with another key or mouse action cancels a pending tap. Release the second held press to end cycling. Keyboard auto-repeat does not count as a new tap.

The default tap wait is **100 ms**: start the second press within that window after releasing the first. B waits for the same window, preventing an extra B before cycling. The default maximum short-press duration is 300 ms. Each profile can use its own timings. Windows scheduling may add a little to the wait.

## Config

- **Enable Alt Clip Ctrl:** persistent global on/off switch.
- **Auto-detect Clip Studio Paint:** on by default, limiting bindings to CSP. Off lets bindings work in other foreground apps too. The helper's own windows, including Config and key recording, are always excluded.
- **Alt / Ctrl / Shift tabs:** enable or disable each modifier independently. Change forward/backward input keys, tap output, held-input outputs, timings, and the separate `_` / `-_` action selectors. Scroll the profile panel to reach timings and help.
- **Record:** press a keyboard key or combination instead of typing its name. Rotation inputs must be single keys. Outputs support combinations such as `Ctrl+Shift+F1`. You can also type names such as `Space`, `Escape`, `Plus`, or `Minus`; Win combinations can be typed manually.
- **Alt cycle / Ctrl cycle / Shift cycle:** three independent lists with separate remembered positions. Edit names and shortcuts, reorder rows, add rows at the bottom, or remove tools. Each list supports 1-64 tools with unique names and shortcuts within that list. Different cycles may share shortcuts.
- **Notation:** explains `-`, `_`, `-_`, and `+` with examples.
- **Restore defaults:** fills the dialog with defaults. Save applies them; Cancel leaves the running config unchanged.

### Hold actions and scrolling

For each modifier, `_` and `-_` have independent action choices:

| Action | Result |
| --- | --- |
| Original modifier (`_` only, default) | Normal native Alt/Ctrl/Shift; the configured forward/backward outputs remain available. |
| Cycle list | Turning the dial moves through that modifier's configured list. |
| Dial scrolling | Forward sends one scroll-up notch; backward sends one scroll-down notch. |
| Hold a key | Holds the configured key or chord until the gesture ends. Examples: Space, B, Ctrl, Alt, Shift, Ctrl+Shift+F1. |

The default `-_` action remains Cycle list. Existing settings retain their previous behavior. Choosing a custom `_` action replaces that modifier's ordinary native hold. To distinguish a tap from an ordinary custom held key, that key starts after **Maximum short press** (default 300 ms). `-_` held keys start on the second press; dial steps for Cycle list / Dial scrolling act immediately. Custom held outputs are released on gesture release, focus change, pause, disabling, applying settings, or exiting the app. Ordinary native holds remain immediate in Original modifier mode.

The tap and ordinary forward/backward output fields also offer **Scroll up** and **Scroll down** in editable dropdowns. `WheelUp` / `WheelDown` are accepted aliases; modifier combinations such as `Ctrl+Scroll up` can be typed. One output is one standard wheel notch. Rotation inputs still require keyboard keys.

Scrolling acts at the mouse pointer according to the target application's wheel handling. For a color slider, hover over the slider before turning; wheel output does not automatically locate or adjust a color wheel. Example: set `_Ctrl action` to Dial scrolling and `-_Ctrl action` to Cycle list to use the same dial for both.

Save writes **AltClipCtrl.settings.xml** beside the executable. Keep that file when upgrading to retain your settings. No keystroke history is written. The included **AltClipCtrl.settings.example.xml** shows default settings but is not loaded automatically. If Save fails, move the app to a writable folder.

## Tools and tracking

Alt, Ctrl and Shift each use their own cycle. For example, cycling Alt to Brush, then cycling Ctrl, leaves Alt at Brush; returning to Alt continues from there. All three start with the existing 20-tool order, and can be customized independently in Config. Existing v1.0 settings are migrated automatically by copying the old list into each cycle. Saving Config writes the new format; keep a backup if you need to return to v1.0.

Default order:

| Shortcut | Tool | Shortcut | Tool |
|---|---|---|---|
| 1 | Pen | F2 | Auto select |
| 2 | Sketch | F3 | Gradient |
| 3 | Blend | F4 | Operation |
| 4 | Brush | F5 | Figure |
| 5 | Eraser | F6 | Text |
| 6 | Airbrush | F7 | Comic |
| 7 | Liquify | F8 | Ruler |
| 8 | Decoration | F9 | Correct line |
| 9 | Selection area | F10 | Move |
| F1 | Fill | F11 | Eyedropper |

The app observes configured tool shortcuts used directly on your keyboard or controller, including modifier combinations. A direct shortcut updates each cycle containing that shortcut, at its own matching row. Cycling and mapped gesture outputs update only the modifier that issued them, even when another cycle contains the same shortcut. Mouse selections and unknown shortcuts cannot be identified directly: CSP does not expose its current tool through a supported simple query. After a mouse selection, press that tool's configured shortcut to resync. The old Match tracker button and menu are removed.

The app remembers requested selections; it cannot confirm CSP accepted them. Each cycle wraps independently. When its position is unknown, first next selects its first listed tool and first previous selects its last. An unknown tap output such as default B resets only that modifier's position; other unmapped held outputs retain its latest position. The main window shows all three positions. The tray command **Forget all cycle positions** resets all three.

Set corresponding shortcuts in CSP yourself. Remove collisions with menu, palette, group, or individual-tool shortcuts. This helper does not change CSP settings. Use with the canvas active, outside dialogs/text editing and between brush strokes. Pause while changing CSP shortcuts. When auto-detection is off, tool tracking observes the same keys in other apps too and cannot imply CSP's active tool.

## Dial and responsiveness

Keep your dial button assigned to the modifier for the profile you use, and rotation to that modifier plus its configured forward/backward keys. The button should report down on pressing and up on releasing. Software-generated input is accepted; only this helper's own marked output is ignored.

The optimized event path retains rapid injected notches and balanced nested modifier+bracket packets. Currently held keys are cached; tool outputs are prepared in advance. Tracking updates on each step; window/tray refreshes are grouped about 40 ms apart. There is no intentional cycling delay. Unusual HID or firmware behavior still requires checking on the actual dial.

## Privacy and limitations

No network code, clipboard access, keystroke log, startup entry, registry changes, or automatic updater. Current held-key state, gestures, and the three cycle positions stay in memory. Only settings explicitly saved through Config are persisted. Temporary keyboard/mouse listeners are installed in the selected scope and removed when disabled, paused, or outside that scope.

Keep CSP and the helper at normal privileges; Windows may block input sent to a more privileged app. The executable is unsigned. The icon and source are included. Exit the app and delete its files to remove it.

## Source and build

The source package contains `src/`, `assets/`, `build.ps1`, `test.ps1`, this README, and a sample settings file. The public repository is [SimplePhilipp/Alt-Clip-Ctrl](https://github.com/SimplePhilipp/Alt-Clip-Ctrl). Generated executables, test reports, and personal settings are excluded by `.gitignore`.

Build locally in PowerShell:

```powershell
.\build.ps1
```

This uses Microsoft's .NET Framework C# compiler already on Windows and produces `bin/AltClipCtrl.exe`. No package installation or network access is used. Then run:

```powershell
.\test.ps1
.\test.ps1 -Smoke
```

The smoke test initializes the app and Config tabs, produces preview images, and exits without sending keys. Test output goes to `test-results/`.

## Verification

Checked: all hold/tap-hold action choices and XML/UI round-trips; wheel direction, notch count and output tagging; held key/chord down/up balance and cleanup on release, disabling, scope changes, applying settings and shutdown using diagnostic input capture; independent cycles and migration; gesture regressions and simulated dial sequences; native modifier holds and shortcuts; custom bindings and output modifier restoration. Diagnostic tests send no real keys or scroll events.

The rendered UI was visually checked. Actual selection and latency in CSP still need testing with your dial and workspace. No hardware performance result is claimed. Diagnostic command-line modes are `--self-test <report-path>` and `--smoke-test <report-path>`; the latter also writes UI previews beside its report.

## Config preview

![Alt Clip Ctrl configuration](docs/config.png)


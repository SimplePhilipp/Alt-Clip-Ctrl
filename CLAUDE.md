# Alt Clip Ctrl handover

Handover prepared 2026-11-01. This repository contains the current source for **Alt Clip Ctrl 2.2.1**. The app was previously named Inbetween; the legacy modifier-based Windows helper remains in `src/`.

## Latest change

The user could not find the combined hold and dial action. Both **Hold (_)** and **Tap then hold (−_)** now always show **Without turning** first and **With dial** directly underneath. There is no combination selector to discover. Tap remains unchanged. See `docs/altclipctrl-hold-visible.png`.

`ActionEditor(separate_dial=True)` in `altclipctrl/ui.py` wraps existing assignments for editing and hides the outer kind selector. A single active section saves back to its original action format; two active sections save as `hold_dial`. Existing assignments reopen in the correct sections. Without turning supports No action, Hold a key, and Switch profile. With dial supports No action, Dial scrolling, Dial cycling, and Dial modifier. Switching profile ends a hold and cannot be combined with an active dial section; the dialog displays a validation message.

The engine behavior from 2.2.0 is unchanged: holding can keep an output such as Space down; the first dial turn releases that output before activating the dial mode until button release. A dial press alone does not trigger the transition. Other holders of the same key retain their own hold.

## User requirements to preserve

- White controller schematic with black outlines; no drawn button names, user names on hover.
- Five dial signals, left to right: pressed counterclockwise, counterclockwise, pressed neutral, clockwise, pressed clockwise.
- Three most recent actions, input highlighting, no flicker during a held button.
- Profiles, application links, profile switching, and F1–F24.
- Multiple named cycle lists per profile, selected per action; shared shortcuts synchronize matching lists while unmatched lists keep their position.
- Dial scrolling/cycling direction reversal and temporary dial modifier mappings while a button is held.
- Optional scroll acceleration checkbox and adjustable factor. Preserve immediate first-step delivery and avoid introducing a slow ramp or queued inertia. Earlier perceived scrolling delay was investigated; the user later thought it was their perception, so no unresolved diagnosis is asserted here.
- Windows, Linux, and macOS support. Linux/macOS still need real hardware validation.

## Structure and settings

- `altclipctrl/ui.py`: PySide6 interface, action editor, binding dialog, inline five-button dial modifier editor.
- `altclipctrl/engine.py`, `model.py`: gesture processing, actions, profiles, named cycle lists, validation.
- `altclipctrl/storage.py`: persistence and migration. Preserve existing settings and original legacy files.
- `inbetween/`: compatibility entry point; `src/`: previous Windows helper.
- JSON schema version 2 stores profile `cycle_lists`; old single-list settings migrate to a Default list. Action references use cycle IDs, not list names.
- Windows live input runs separately from the UI. Preserve output ordering and held-key reference counts. Native tests use an isolated receiver; do not send test shortcuts to the user's applications.

Use `--settings PATH` for isolated runs and `--preview` for UI work without global input/output. Do not edit or overwrite the user's live settings or backup to test a change. Close older running copies before a live run; the app has single-instance guards.

## Validation and builds

Install `requirements-altclipctrl.txt` into a virtual environment (Python 3.10–3.13). Run:

```text
python -m unittest discover -s tests -p "test_*.py"
python -m tests.ui_smoke
python build-altclipctrl.py
python package-altclipctrl.py
```

The 2.2.1 work passed **140 unit tests**, the offscreen UI smoke suite, and packaged Windows startup/render/listener shutdown smoke checks. A regression in `tests/test_hold_dial.py` verifies both held gestures show the two sections immediately and preserve existing actions. Tests may regenerate documentation screenshots. Hardware interaction was not revalidated on Linux or macOS.

Windows packaging used PySide6 Essentials 6.8.3 and PyInstaller 6.16.0. Keep `_internal` beside the executable. Output ZIPs are generated in `outputs/`, which is ignored by Git; a source push does not upload a GitHub Release.

## Local workspace at handover

The earlier chat removed the old checkout at the user's request. This push uses the fresh `Git-Publish/` checkout under `C:/Users/Gebruiker/Desktop/CSP-Tool-Cycler-Windows`. The previously tested source and build environment remain in sibling `Development/`. The sibling `AltClipCtrl-2.2.1/` holds the built app; root Windows/source ZIPs contain the 2.2.1 build. `AltClipCtrl-App/` is the older copy; `Settings-backup/` contains the user's preserved settings.

Do not assume the workspace root is the Git checkout. Do not remove those directories as incidental cleanup. Automatic approval previously rejected deleting `Development/` because it contains modified source and tests; it was left intact. No new feature request is pending beyond publishing this update and providing this handover.

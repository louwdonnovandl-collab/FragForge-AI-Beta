# FragForge AI v0.10.14 — Properties scroll-wheel fix

Based on the confirmed-working v0.10.13 combined upgrade.

## Fix
Hovering over a slider, numeric field or dropdown in the right-hand Properties panel now scrolls the panel instead of changing that control. Click the control first to enable mouse-wheel adjustments; clicking elsewhere removes that control’s wheel adjustment focus. Direct dragging, keyboard entry and selection still work.

## Installation
Replace the GitHub source with these files and run the existing Windows build workflow. All v0.10.13 functionality is preserved.

## Testing
1. Hover over Clip Speed or Overlay Opacity and scroll: the Properties panel should move, without changing the value.
2. Click the control and scroll: its value should change.
3. Click elsewhere and hover-scroll again: the Properties panel should move.

Python syntax and ZIP integrity checked. Windows GUI behavior requires local testing.

## Startup crash hotfix
Fixed `QObject.findChildren(tuple)` by searching each supported widget type separately. This avoids the PySide6 startup TypeError.

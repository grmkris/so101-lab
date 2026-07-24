"""Does pynput capture keys in THIS terminal? Run it, type some keys.
If they print -> DAgger's tab/space will work. If nothing prints -> grant
Accessibility permission to your terminal app, quit+reopen it, re-test."""
from pynput import keyboard

print("Type keys now (tab, space, arrows). Esc to quit.")
print("If NOTHING prints when you type -> Accessibility permission is missing.\n", flush=True)

def on_press(key):
    print("captured:", key, flush=True)
    if key == keyboard.Key.esc:
        return False

with keyboard.Listener(on_press=on_press) as listener:
    listener.join()
print("done.")

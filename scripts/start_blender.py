"""Open a scratch Blender scene with a rig, receiver and managed sender."""

import argparse
import atexit
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import bpy
from mathutils import Euler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import leap_live_link
from leap_live_link.operator import receiver

parser = argparse.ArgumentParser()
parser.add_argument("--demo", action="store_true")
parser.add_argument("--port", type=int, default=9009)
parser.add_argument("--mode", default="desktop")
args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

leap_live_link.register()
scene = bpy.context.scene
scene.leap_port = args.port
# This script is launched with factory startup into a new scratch scene.
for obj in list(scene.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
bpy.ops.leap.create_debug_hand()
receiver.start(scene, bpy.context.window_manager)

for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            space = area.spaces.active
            space.show_region_ui = True
            space.overlay.show_floor = True
            space.region_3d.view_distance = 0.85
            space.region_3d.view_location = (0, 0.02, 0.20)
            space.region_3d.view_rotation = Euler((math.radians(45), 0, 0)).to_quaternion()
            space.overlay.grid_scale = 0.1
            space.clip_start = 0.001

output = ROOT / ".test-output"
output.mkdir(exist_ok=True)
log = (output / "sender.log").open("w", encoding="utf-8")
command = [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-u", str(ROOT / "sender" / "sender.py"), "--port", str(args.port), "--mode", args.mode]
if args.demo:
    command.append("--demo")
sender = subprocess.Popen(command, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def cleanup():
    if sender.poll() is None:
        sender.terminate()
        try:
            sender.wait(timeout=3)
        except subprocess.TimeoutExpired:
            sender.kill()
            sender.wait(timeout=3)
    log.close()


atexit.register(cleanup)


def update_status():
    status = {
        "blender": bpy.app.version_string,
        "sender_pid": sender.pid,
        "sender_exit_code": sender.poll(),
        "receiver_running": receiver.sock is not None,
        "updates": receiver.frames,
        "hands": receiver.hands,
        "source": receiver.source,
        "packet_age": time.monotonic() - receiver.last_packet if receiver.last_packet else None,
        "status": bpy.context.window_manager.leap_status,
    }
    (output / "live-status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    if sender.poll() is not None and receiver.sock:
        receiver.stop()
        bpy.context.window_manager.leap_status = "Sender stopped; see .test-output/sender.log"
    return 1.0


bpy.app.timers.register(update_status, first_interval=1)
print("Leap Link ready. Open the Leap Link sidebar tab to see connection status.")

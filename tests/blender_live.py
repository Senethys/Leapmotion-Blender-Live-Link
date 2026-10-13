"""Optional real-controller UDP/pose check; run inside Blender on Windows."""

from pathlib import Path
import socket
import subprocess
import sys
import time

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import leap_live_link
from leap_live_link import operator as link

leap_live_link.register()
bpy.ops.leap.create_debug_hand()
scene = bpy.context.scene
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as available:
    available.bind(("127.0.0.1", 0))
    scene.leap_port = available.getsockname()[1]
link.receiver.start(scene, bpy.context.window_manager)
proc = subprocess.Popen([
    str(ROOT / ".venv" / "Scripts" / "python.exe"),
    str(ROOT / "sender" / "sender.py"), "--duration", "12", "--port", str(scene.leap_port),
], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
start = time.monotonic()
frames_with_hands = 0
max_error = 0
motion = 0
previous_tip = None
try:
    while time.monotonic() - start < 10:
        frame = link.receiver.receive()
        if frame and frame["hands"]:
            frames_with_hands += 1
            bpy.context.view_layer.update()
            for hand in frame["hands"]:
                prefix = "L" if hand["type"] == "Left" else "R"
                for finger, bones in hand["fingers"].items():
                    for kind, bone in bones.items():
                        pb = scene.leap_target_rig.pose.bones[f"{prefix}_{finger}_{kind}"]
                        for actual, tracked in ((pb.head, bone["position"]), (pb.tail, bone["next_joint"])):
                            error = (actual - link.convert_position(tracked, scene.leap_scale)).length
                            max_error = max(max_error, error)
                            if error > 2e-5:
                                raise AssertionError(f"Live joint mismatch: {pb.name}: {error}")
            tip = scene.leap_target_rig.pose.bones['R_Index_Distal'].tail.copy()
            if previous_tip is not None:
                motion += (tip - previous_tip).length
            previous_tip = tip
        if proc.poll() is not None:
            raise RuntimeError(f"Live sender exited with code {proc.returncode}")
        time.sleep(0.01)
    if not frames_with_hands:
        raise RuntimeError("No hands seen during the live check; place a hand over the controller")
    print(f"LIVE BLENDER CHECK PASSED: {frames_with_hands} hand frames, max joint error={max_error:.9f} units, right index path={motion:.4f} units")
finally:
    proc.terminate()
    proc.wait(timeout=5)
    leap_live_link.unregister()

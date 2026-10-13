"""Run with Blender --background --factory-startup --python-exit-code 1."""

import copy
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest

import bpy
from mathutils import Quaternion, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import leap_live_link
from leap_live_link import operator as link
from sender.sender import demo_frame


class BlenderIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        leap_live_link.register()
        bpy.ops.leap.create_debug_hand()
        cls.scene = bpy.context.scene
        cls.rig = cls.scene.leap_target_rig

    @classmethod
    def tearDownClass(cls):
        leap_live_link.unregister()

    def tearDown(self):
        link.receiver.stop()

    def assert_vector(self, actual, expected):
        self.assertLess((actual - expected).length, 2e-6, f"{actual} != {expected}")

    def verify_joints(self, frame):
        link.apply_pose(self.scene, link.validate_frame(frame))
        bpy.context.view_layer.update()
        for hand in frame["hands"]:
            prefix = "L" if hand["type"] == "Left" else "R"
            wrist = self.rig.pose.bones[f"{prefix}_Wrist"]
            self.assert_vector(wrist.head, link.convert_position(hand["palm_position"], self.scene.leap_scale))
            for finger, bones in hand["fingers"].items():
                for kind, bone in bones.items():
                    pb = self.rig.pose.bones[f"{prefix}_{finger}_{kind}"]
                    self.assert_vector(pb.head, link.convert_position(bone["position"], self.scene.leap_scale))
                    self.assert_vector(pb.tail, link.convert_position(bone["next_joint"], self.scene.leap_scale))

    def test_joint_positions_and_lengths_across_frames(self):
        self.assertEqual(len(self.rig.data.bones), 44)
        for t in (0, 0.5, 2, 5):
            self.verify_joints(demo_frame(t))

    def test_rotated_palms_and_zero_thumb_metacarpal(self):
        frame = demo_frame(0.7)
        rotation = Quaternion(Vector((0.4, 0.7, 0.3)).normalized(), 1.2)
        for hand in frame["hands"]:
            hand["palm_rotation"] = list(rotation)
            for bones in hand["fingers"].values():
                for bone in bones.values():
                    bone["position"] = list(rotation @ Vector(bone["position"]))
                    bone["next_joint"] = list(rotation @ Vector(bone["next_joint"]))
                    bone["rotation"] = list(rotation)
            metacarpal = hand["fingers"]["Thumb"]["Metacarpal"]
            metacarpal["next_joint"] = metacarpal["position"][:]
        self.verify_joints(frame)
        for hand in frame["hands"]:
            prefix = "L" if hand["type"] == "Left" else "R"
            actual = self.rig.pose.bones[f"{prefix}_Wrist"].matrix.to_3x3()
            expected = link.convert_rotation(hand["palm_rotation"])
            for i in range(3):
                self.assert_vector(actual.col[i], expected.col[i])

    def test_scale_and_object_origin(self):
        old_scale = self.scene.leap_scale
        self.scene.leap_scale = 0.002
        self.rig.location = (2, 3, 4)
        self.rig.rotation_euler = (0.2, 0.4, 0.1)
        try:
            self.verify_joints(demo_frame(0.4))
        finally:
            self.scene.leap_scale = old_scale
            self.rig.location = (0, 0, 0)
            self.rig.rotation_euler = (0, 0, 0)

    def test_validation(self):
        invalid = [[], {}, {"version": 2, "hands": []}, {"hands": [None]}, {"hands": "bad"}]
        for coordinate in (float('nan'), float('inf'), "1", None, True):
            frame = demo_frame(0)
            frame["hands"][0]["palm_position"][0] = coordinate
            invalid.append(frame)
        frame = demo_frame(0)
        frame["hands"][0]["palm_rotation"] = [0, 0, 0, 0]
        invalid.append(frame)
        frame = demo_frame(0)
        frame["hands"].append(copy.deepcopy(frame["hands"][0]))
        invalid.append(frame)
        for frame in invalid:
            with self.assertRaises(ValueError):
                link.validate_frame(frame)

    def test_udp_latest_valid_frame_empty_hands_and_restart(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as available:
            available.bind(("127.0.0.1", 0))
            self.scene.leap_port = available.getsockname()[1]
        link.receiver.start(self.scene, bpy.context.window_manager)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            for frame in (demo_frame(0), demo_frame(0.8)):
                sender.sendto(json.dumps(frame).encode(), ("127.0.0.1", self.scene.leap_port))
            sender.sendto(b'{bad json}', ("127.0.0.1", self.scene.leap_port))
            time.sleep(0.02)
            result = link.receiver.receive()
            self.assertEqual(result["hands"], demo_frame(0.8)["hands"])
            self.assertEqual(link.receiver.invalid, 1)
            sender.sendto(b'{"hands": []}', ("127.0.0.1", self.scene.leap_port))
            time.sleep(0.02)
            self.assertEqual(link.receiver.receive()["hands"], [])
            self.assertEqual(link.receiver.hands, 0)
        link.receiver.last_packet = time.monotonic() - 2
        link.receiver.tick()
        self.assertIn("No recent data", bpy.context.window_manager.leap_status)
        link.receiver.stop()
        self.assertFalse(bpy.app.timers.is_registered(link.receiver.callback))
        link.receiver.start(self.scene, bpy.context.window_manager)
        link.stop_on_load(None)
        self.assertIsNone(link.receiver.sock)
        link.receiver.start(self.scene, bpy.context.window_manager)

    def test_port_conflict(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            self.scene.leap_port = occupied.getsockname()[1]
            with self.assertRaises(OSError):
                link.receiver.start(self.scene, bpy.context.window_manager)
            self.assertIsNone(link.receiver.sock)
            self.assertFalse(bpy.context.window_manager.leap_listening)

    def test_external_sender_to_blender(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as available:
            available.bind(("127.0.0.1", 0))
            self.scene.leap_port = available.getsockname()[1]
        link.receiver.start(self.scene, bpy.context.window_manager)
        python = ROOT / ".venv" / "Scripts" / "python.exe"
        proc = subprocess.Popen([str(python), str(ROOT / "sender" / "sender.py"), "--demo", "--duration", "0.5", "--port", str(self.scene.leap_port)])
        try:
            while proc.poll() is None:
                link.receiver.receive()
                time.sleep(0.01)
            link.receiver.receive()
            self.assertEqual(proc.returncode, 0)
            self.assertGreater(link.receiver.frames, 5)
            self.assertEqual(link.receiver.hands, 2)
            self.assertEqual(link.receiver.source, "Demo")
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BlenderIntegration))
    if not result.wasSuccessful():
        raise RuntimeError("Blender integration tests failed")
    # Register again to verify complete add-on teardown/re-enable.
    leap_live_link.register()
    leap_live_link.unregister()
    print("BLENDER INTEGRATION PASSED", bpy.app.version_string)

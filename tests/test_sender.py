"""Native ABI and serializer checks (no controller required)."""

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sender.leap_runtime import load_leapc
from sender.sender import format_hand


class NativeABI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ffi, cls.lib, cls.path = load_leapc()

    def test_tracking_struct_layout(self):
        # Sizes in the packed, 64-bit Orion and Hyperion tracking ABI.
        self.assertEqual(self.ffi.sizeof("LEAP_BONE"), 44)
        self.assertEqual(self.ffi.sizeof("LEAP_DIGIT"), 184)
        self.assertEqual(self.ffi.sizeof("LEAP_PALM"), 80)
        self.assertEqual(self.ffi.sizeof("LEAP_HAND"), 1084)
        self.assertEqual(self.ffi.offsetof("LEAP_HAND", "arm"), 1040)
        self.assertEqual(self.ffi.offsetof("LEAP_TRACKING_EVENT", "pHands"), 36)

    def test_native_serialization(self):
        hand = self.ffi.new("LEAP_HAND *")
        hand.id = 7
        hand.type = 1
        hand.palm.position.y = 200
        hand.palm.orientation.w = 1
        bone = hand.digits[1].bones[0]
        bone.prev_joint.x = 10
        bone.next_joint.x = 40
        bone.width = 13
        bone.rotation.w = 0.5
        bone.rotation.x = math.sqrt(0.75)
        data = format_hand(hand[0])
        self.assertEqual(data["type"], "Right")
        self.assertEqual(data["palm_position"], [0, 200, 0])
        self.assertEqual(len(data["fingers"]), 5)
        output = data["fingers"]["Index"]["Metacarpal"]
        self.assertEqual(output["length"], 30)
        self.assertEqual(output["width"], 13)
        self.assertEqual(output["rotation"][0], 0.5)


if __name__ == "__main__":
    unittest.main()

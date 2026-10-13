"""Stream LeapC hand frames to Blender over local UDP, or run a hardware-free demo."""

import argparse
import json
import math
import socket
import sys
import time

FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
BONES = ("Metacarpal", "Proximal", "Intermediate", "Distal")


def vector(value):
    return [float(value.x), float(value.y), float(value.z)]


def quaternion(value):
    return [float(value.w), float(value.x), float(value.y), float(value.z)]


def format_bone(bone):
    start, end = vector(bone.prev_joint), vector(bone.next_joint)
    return {
        "rotation": quaternion(bone.rotation),
        "position": start,
        "next_joint": end,
        "width": float(bone.width),
        "length": math.dist(start, end),
    }


def format_hand(hand):
    # LeapC hand type is 0 = left, 1 = right. Quaternions on the wire are WXYZ.
    return {
        "id": int(hand.id),
        "type": "Left" if int(hand.type) == 0 else "Right",
        "palm_position": vector(hand.palm.position),
        "palm_rotation": quaternion(hand.palm.orientation),
        "fingers": {
            name: {kind: format_bone(digit.bones[j]) for j, kind in enumerate(BONES)}
            for name, digit in zip(FINGERS, hand.digits)
        },
        "arm": format_bone(hand.arm),
    }


def demo_frame(elapsed):
    """Two articulated hands in Leap's millimetre, Y-up coordinate system."""
    hands = []
    for side, sign in (("Left", -1), ("Right", 1)):
        palm = [sign * 110 + 25 * math.sin(elapsed), 220 + 25 * math.cos(elapsed), 0]
        fingers = {}
        curl = 0.65 + 0.6 * math.sin(elapsed * 2)
        for index, finger in enumerate(FINGERS):
            start = [palm[0] + sign * (index - 2) * 19, palm[1], -20]
            bones = {}
            for joint, kind in enumerate(BONES):
                length = (30, 38, 25, 20)[joint] * (0.8 if index == 0 else 1)
                angle = curl * joint * 0.55
                end = [start[0], start[1] - length * math.sin(angle), start[2] - length * math.cos(angle)]
                bones[kind] = {"position": start, "next_joint": end, "rotation": [1, 0, 0, 0], "width": 12, "length": length}
                start = end
            fingers[finger] = bones
        hands.append({
            "id": 1 if sign < 0 else 2, "type": side,
            "palm_position": palm, "palm_rotation": [1, 0, 0, 0], "fingers": fingers,
            "arm": {"position": [palm[0], palm[1] - 40, 180], "next_joint": palm, "rotation": [1, 0, 0, 0]},
        })
    return {"version": 1, "source": "demo", "timestamp": time.time(), "hands": hands}


def send_frame(sock, destination, frame):
    sock.sendto(json.dumps(frame, separators=(",", ":"), allow_nan=False).encode("utf-8"), destination)


def run_demo(args, sock):
    print(f"DEMO: sending animated hands to {args.host}:{args.port}; Ctrl+C stops.", flush=True)
    start = time.monotonic()
    deadline = start
    while not args.duration or time.monotonic() - start < args.duration:
        send_frame(sock, (args.host, args.port), demo_frame(time.monotonic() - start))
        deadline += 1 / args.fps
        time.sleep(max(0, deadline - time.monotonic()))
    return 0


def run_tracking(args, sock):
    try:
        from .leap_runtime import load_leapc
    except ImportError:
        from leap_runtime import load_leapc

    ffi, lib, library = load_leapc(args.sdk)
    print(f"LeapC: {library}", flush=True)
    connection_ptr = ffi.new("LEAP_CONNECTION *")

    def check(result, operation):
        if result != lib.eLeapRS_Success:
            raise RuntimeError(f"{operation} failed (LeapC 0x{result:08X}). Check the Ultraleap tracking service.")

    check(lib.LeapCreateConnection(ffi.NULL, connection_ptr), "Create connection")
    connection = connection_ptr[0]
    connected = device = False
    frames = 0
    hand_count = 0
    start = last_report = time.monotonic()
    try:
        check(lib.LeapOpenConnection(connection), "Open connection")
        print(f"Connecting; sending to {args.host}:{args.port} (Ctrl+C stops).", flush=True)
        message = ffi.new("LEAP_CONNECTION_MESSAGE *")
        while not args.duration or time.monotonic() - start < args.duration:
            result = lib.LeapPollConnection(connection, 100, message)
            if result == lib.eLeapRS_Timeout:
                pass
            else:
                check(result, "Poll connection")
                if message.type == lib.eLeapEventType_Connection:
                    connected = True
                    print("Connected to Leap Motion Service", flush=True)
                    check(lib.LeapSetPolicyFlags(connection, lib.eLeapPolicyFlag_BackgroundFrames, 0), "Enable background frames")
                    if hasattr(lib, "LeapSetTrackingMode"):
                        mode = getattr(lib, {"desktop": "eLeapTrackingMode_Desktop", "hmd": "eLeapTrackingMode_HMD", "screen-top": "eLeapTrackingMode_ScreenTop"}[args.mode])
                        check(lib.LeapSetTrackingMode(connection, mode), "Set tracking mode")
                    else:
                        if args.mode == "screen-top":
                            raise RuntimeError("Screen-top tracking requires Gemini/Hyperion; Orion supports desktop and HMD")
                        hmd = lib.eLeapPolicyFlag_OptimizeHMD
                        check(lib.LeapSetPolicyFlags(connection, hmd if args.mode == "hmd" else 0, hmd if args.mode == "desktop" else 0), "Set Orion tracking policy")
                elif message.type == lib.eLeapEventType_Device:
                    device = True
                    print("Leap Motion controller detected", flush=True)
                elif message.type == lib.eLeapEventType_DeviceLost:
                    device = False
                    send_frame(sock, (args.host, args.port), {"version": 1, "source": "leapc", "hands": []})
                    print("Controller disconnected; waiting for reconnection.", flush=True)
                elif message.type == lib.eLeapEventType_ConnectionLost:
                    raise RuntimeError("Connection to Leap service lost. Restart the service and sender.")
                elif message.type == lib.eLeapEventType_Tracking:
                    event = message.tracking_event
                    # Serialize before the next poll invalidates native frame memory.
                    hands = [format_hand(event.pHands[i]) for i in range(event.nHands)]
                    send_frame(sock, (args.host, args.port), {"version": 1, "source": "leapc", "timestamp": time.time(), "hands": hands})
                    frames += 1
                    hand_count = len(hands)
            now = time.monotonic()
            if now - last_report >= 5:
                status = "service not connected" if not connected else "no controller detected" if not device else f"{frames} frames sent, {hand_count} hands"
                print(status, flush=True)
                last_report = now
            if args.check and connected and device and frames:
                print(f"CHECK OK: service, controller and tracking frames; {hand_count} hands visible.", flush=True)
                return 0
        if args.check:
            raise RuntimeError(f"Check timed out: service connected={connected}, device detected={device}, tracking frames={frames}. Start the tracking service and connect the controller.")
        return 0
    finally:
        lib.LeapCloseConnection(connection)
        lib.LeapDestroyConnection(connection)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="Blender receiver address (default: localhost)")
    parser.add_argument("--port", type=int, default=9009)
    parser.add_argument("--demo", action="store_true", help="Animate synthetic hands without Leap hardware or dependencies")
    parser.add_argument("--check", action="store_true", help="Check native library, service, controller and tracking (10 seconds)")
    parser.add_argument("--sdk", help="SDK folder containing include/LeapC.h and lib/x64/LeapC.dll")
    parser.add_argument("--mode", choices=("desktop", "hmd", "screen-top"), default="desktop")
    parser.add_argument("--fps", type=int, default=60, help="Demo frame rate")
    parser.add_argument("--duration", type=float, default=0, help="Stop after this many seconds; 0 runs until Ctrl+C")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535 or not 1 <= args.fps <= 240 or args.duration < 0:
        parser.error("Port must be 1..65535, FPS 1..240, duration >= 0")
    if args.check and args.demo:
        parser.error("Use --check for hardware or --demo for synthetic data")
    if args.check and not args.duration:
        args.duration = 10
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            return run_demo(args, sock) if args.demo else run_tracking(args, sock)
    except KeyboardInterrupt:
        print("Sender stopped.", flush=True)
        return 0
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        print(f"Sender error: {error}", file=sys.stderr, flush=True)
        if isinstance(error, ImportError):
            print("Install with: .\\.venv\\Scripts\\python.exe -m pip install -r sender/requirements.txt", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

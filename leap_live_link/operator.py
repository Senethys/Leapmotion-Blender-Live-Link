"""Blender-main-thread UDP receiver and armature pose conversion."""

import json
import math
import socket
import time

import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix, Quaternion, Vector

FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
BONE_TYPES = ("Metacarpal", "Proximal", "Intermediate", "Distal")
TO_BLENDER = Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))
# Leap hand local -Z points along the fingers; Blender bone local +Y does.
BONE_AXES = Matrix.Rotation(-math.pi / 2, 3, 'X')
INTERVAL = 1 / 60


def _numbers(value, count):
    if not isinstance(value, (list, tuple)) or len(value) != count:
        raise ValueError(f"Expected {count} coordinates")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e9 for v in value):
        raise ValueError("Coordinates must be finite numbers")
    return value


def validate_frame(frame):
    """Reject malformed packets before any Blender data is changed."""
    if not isinstance(frame, dict) or frame.get("version", 1) != 1:
        raise ValueError("Unsupported Leap frame")
    hands = frame.get("hands")
    if not isinstance(hands, list) or len(hands) > 2:
        raise ValueError("Expected a list of at most two hands")
    sides = set()
    for hand in hands:
        if not isinstance(hand, dict) or hand.get("type") not in ("Left", "Right") or hand["type"] in sides:
            raise ValueError("Invalid or duplicate hand side")
        sides.add(hand["type"])
        _numbers(hand.get("palm_position"), 3)
        rotation = _numbers(hand.get("palm_rotation"), 4)
        if sum(v * v for v in rotation) < 1e-12:
            raise ValueError("Invalid palm quaternion")
        fingers = hand.get("fingers", {})
        if not isinstance(fingers, dict):
            raise ValueError("Invalid fingers")
        for finger, bones in fingers.items():
            if finger not in FINGERS or not isinstance(bones, dict):
                raise ValueError("Unknown finger")
            for kind, bone in bones.items():
                if kind not in BONE_TYPES:
                    raise ValueError("Unknown bone")
                _validate_bone(bone)
        if "arm" in hand:
            _validate_bone(hand["arm"])
    return frame


def _validate_bone(bone):
    if not isinstance(bone, dict):
        raise ValueError("Invalid bone")
    _numbers(bone.get("position"), 3)
    _numbers(bone.get("next_joint"), 3)
    if "rotation" in bone:
        _numbers(bone["rotation"], 4)


def convert_position(position, scale):
    return TO_BLENDER @ (Vector(position) * scale)


def convert_rotation(rotation):
    q = Quaternion(rotation)
    q.normalize()
    return TO_BLENDER @ q.to_matrix() @ BONE_AXES


def _bone_matrix(data, rest_length, scale):
    start = convert_position(data["position"], scale)
    delta = convert_position(data["next_joint"], scale) - start
    if delta.length < 1e-8:
        # Leap's thumb metacarpal legitimately has coincident joints.
        matrix = Matrix.Identity(4)
        matrix[1][1] = 1e-6
    else:
        y_axis = delta.normalized()
        # Preserve roll from the sensor quaternion, with a stable fallback.
        up = convert_rotation(data.get("rotation", [1, 0, 0, 0])).col[2]
        z_axis = up - y_axis * up.dot(y_axis)
        if z_axis.length < 1e-6:
            up = Vector((1, 0, 0)) if abs(y_axis.x) < 0.9 else Vector((0, 0, 1))
            z_axis = up - y_axis * up.dot(y_axis)
        z_axis.normalize()
        x_axis = y_axis.cross(z_axis).normalized()
        matrix = Matrix((x_axis, y_axis * (delta.length / rest_length), z_axis)).transposed().to_4x4()
    matrix.translation = start
    return matrix


def apply_pose(scene, frame):
    rig = scene.leap_target_rig
    if not rig or rig.type != 'ARMATURE':
        return
    if rig.mode == 'EDIT':
        raise ValueError("Leave Edit Mode to receive poses")
    desired = {}
    for hand in frame["hands"]:
        prefix = "L" if hand["type"] == "Left" else "R"
        wrist = convert_rotation(hand["palm_rotation"]).to_4x4()
        wrist.translation = convert_position(hand["palm_position"], scene.leap_scale)
        desired[f"{prefix}_Wrist"] = wrist
        for finger, bones in hand.get("fingers", {}).items():
            for kind, data in bones.items():
                name = f"{prefix}_{finger}_{kind}"
                pb = rig.pose.bones.get(name)
                if pb:
                    desired[name] = _bone_matrix(data, pb.bone.length, scene.leap_scale)
        name = f"{prefix}_Forearm"
        pb = rig.pose.bones.get(name)
        if pb and "arm" in hand:
            desired[name] = _bone_matrix(hand["arm"], pb.bone.length, scene.leap_scale)

    # Compute parent-relative bases explicitly. Setting .matrix in a loop can
    # read a parent's old evaluated pose and distort an entire finger chain.
    def update_bone(pb, parent_matrix=None):
        matrix = desired.get(pb.name)
        kwargs = {}
        if pb.parent:
            kwargs = {"parent_matrix": parent_matrix, "parent_matrix_local": pb.parent.bone.matrix_local}
        if matrix is not None:
            pb.matrix_basis = pb.bone.convert_local_to_pose(matrix, pb.bone.matrix_local, invert=True, **kwargs)
        else:
            matrix = pb.bone.convert_local_to_pose(pb.matrix_basis, pb.bone.matrix_local, **kwargs)
        for child in pb.children:
            update_bone(child, matrix)

    for pb in rig.pose.bones:
        if pb.parent is None:
            update_bone(pb)
    rig.update_tag(refresh={'OBJECT'})


class Receiver:
    def __init__(self):
        self.sock = None
        self.scene = None
        self.wm = None
        self.last_packet = 0
        self.started = 0
        self.frames = 0
        self.invalid = 0
        self.hands = 0
        self.source = ""
        # Keep one bound method for timer registration and unregistration.
        self.callback = self.tick

    def start(self, scene, wm):
        if self.sock is not None:
            raise ValueError("Receiver is already running")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setblocking(False)
            # Prevent another process from taking our UDP port on Windows.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(("127.0.0.1", scene.leap_port))
        except Exception:
            sock.close()
            raise
        self.sock, self.scene, self.wm = sock, scene, wm
        self.last_packet = self.frames = self.invalid = self.hands = 0
        self.source = ""
        self.started = time.monotonic()
        wm.leap_listening = True
        wm.leap_status = f"Waiting on 127.0.0.1:{scene.leap_port}"
        try:
            bpy.app.timers.register(self.callback, first_interval=INTERVAL)
        except Exception:
            self.stop()
            raise

    def stop(self):
        if bpy.app.timers.is_registered(self.callback):
            bpy.app.timers.unregister(self.callback)
        if self.sock:
            self.sock.close()
        self.sock = None
        try:
            if self.wm:
                self.wm.leap_listening = False
                self.wm.leap_status = "Stopped"
        except (ReferenceError, AttributeError):
            pass
        self.scene = self.wm = None

    def receive(self):
        latest = None
        # Bound the work per tick; apply only the newest valid queued frame.
        for _ in range(256):
            try:
                payload, _address = self.sock.recvfrom(65535)
            except BlockingIOError:
                break
            try:
                latest = validate_frame(json.loads(payload))
            except (ValueError, TypeError, UnicodeError, RecursionError):
                self.invalid += 1
        if latest is not None:
            apply_pose(self.scene, latest)
            self.frames += 1
            self.hands = len(latest["hands"])
            self.source = "Demo" if latest.get("source") == "demo" else "Leap"
            self.last_packet = time.monotonic()
        return latest

    def tick(self):
        if self.sock is None:
            return None
        try:
            if not self.wm.leap_listening:
                self.stop()
                return None
            self.receive()
            if not self.scene.leap_target_rig:
                status = "Choose a target rig"
            elif not self.last_packet:
                status = "Waiting for sender"
            elif time.monotonic() - self.last_packet > 1:
                status = "No recent data; last pose held"
            else:
                status = f"{self.source}: {self.hands} hands | {self.frames} updates"
            if self.invalid:
                status += f" | {self.invalid} invalid"
            self.wm.leap_status = status
            for window in self.wm.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        except (OSError, ReferenceError, ValueError, AttributeError) as error:
            wm = self.wm
            self.stop()
            try:
                wm.leap_status = f"Receiver stopped: {error}"
            except (ReferenceError, AttributeError):
                pass
            return None
        return INTERVAL


receiver = Receiver()


@persistent
def stop_on_load(_unused):
    receiver.stop()


class LEAP_OT_CreateDebugHand(bpy.types.Operator):
    bl_idname = "leap.create_debug_hand"
    bl_label = "Generate Debug Hands"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def execute(self, context):
        existing = context.scene.leap_target_rig
        if existing and existing.type == 'ARMATURE' and existing.get("leap_debug_rig"):
            self.report({'INFO'}, "Debug rig already exists")
            return {'FINISHED'}
        armature = bpy.data.armatures.new("Leap_Debug_Rig_Data")
        rig = bpy.data.objects.new("Leap_Debug_Rig", armature)
        context.collection.objects.link(rig)
        rig["leap_debug_rig"] = True
        rig.show_in_front = True
        armature.display_type = 'STICK'
        for obj in context.selected_objects:
            obj.select_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            for prefix, sign in (("L", -1), ("R", 1)):
                x = sign * 0.11
                wrist = armature.edit_bones.new(f"{prefix}_Wrist")
                wrist.head, wrist.tail = (x, 0, 0.22), (x, 0.05, 0.22)
                arm = armature.edit_bones.new(f"{prefix}_Forearm")
                arm.head, arm.tail = (x, -0.18, 0.18), (x, 0, 0.22)
                for index, finger in enumerate(FINGERS):
                    parent = wrist
                    fx = x + sign * (index - 2) * 0.019
                    fy = 0.02
                    for kind, length in zip(BONE_TYPES, (0.03, 0.038, 0.025, 0.02)):
                        bone = armature.edit_bones.new(f"{prefix}_{finger}_{kind}")
                        bone.parent = parent
                        # Sensor joints translate independently; connected heads
                        # would be forced onto their parent's tail by Blender.
                        bone.use_connect = False
                        bone.inherit_scale = 'NONE'
                        bone.head, bone.tail = (fx, fy, 0.22), (fx, fy + length, 0.22)
                        fy += length
                        parent = bone
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
        context.scene.leap_target_rig = rig
        return {'FINISHED'}


class LEAP_OT_StartReceiver(bpy.types.Operator):
    bl_idname = "leap.start_receiver"
    bl_label = "Start Receiver"

    def execute(self, context):
        rig = context.scene.leap_target_rig
        if not rig or rig.type != 'ARMATURE' or rig.mode == 'EDIT':
            self.report({'ERROR'}, "Choose an armature in Object or Pose Mode first")
            return {'CANCELLED'}
        try:
            receiver.start(context.scene, context.window_manager)
        except (OSError, ValueError) as error:
            self.report({'ERROR'}, f"Could not start receiver: {error}")
            return {'CANCELLED'}
        return {'FINISHED'}


class LEAP_OT_StopReceiver(bpy.types.Operator):
    bl_idname = "leap.stop_receiver"
    bl_label = "Stop Receiver"

    def execute(self, context):
        receiver.stop()
        return {'FINISHED'}


CLASSES = (LEAP_OT_CreateDebugHand, LEAP_OT_StartReceiver, LEAP_OT_StopReceiver)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.handlers.load_pre.append(stop_on_load)


def unregister():
    receiver.stop()
    if stop_on_load in bpy.app.handlers.load_pre:
        bpy.app.handlers.load_pre.remove(stop_on_load)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

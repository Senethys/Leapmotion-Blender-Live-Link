import bpy


def armature_only(_self, obj):
    return obj.type == 'ARMATURE'


class LEAP_PT_Panel(bpy.types.Panel):
    bl_label = "Leap Motion Link"
    bl_idname = "LEAP_PT_Panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Leap Link"

    def draw(self, context):
        layout = self.layout
        scene, wm = context.scene, context.window_manager
        settings = layout.column()
        settings.enabled = not wm.leap_listening
        settings.prop(scene, "leap_port")
        settings.prop(scene, "leap_target_rig")
        settings.prop(scene, "leap_scale")
        layout.label(text=wm.leap_status)
        if wm.leap_listening:
            layout.operator("leap.stop_receiver", icon='PAUSE')
        else:
            layout.operator("leap.start_receiver", icon='PLAY')
        layout.separator()
        layout.operator("leap.create_debug_hand", icon='ARMATURE_DATA')
        layout.label(text="Sender runs outside Blender", icon='INFO')


def register():
    bpy.types.Scene.leap_port = bpy.props.IntProperty(name="UDP Port", default=9009, min=1, max=65535)
    bpy.types.Scene.leap_target_rig = bpy.props.PointerProperty(name="Target Rig", type=bpy.types.Object, poll=armature_only)
    bpy.types.Scene.leap_scale = bpy.props.FloatProperty(name="Units per mm", description="Tracking scale in armature space; 0.001 gives metre-sized hands", default=0.001, min=0.000001, max=1, precision=6)
    bpy.types.WindowManager.leap_listening = bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})
    bpy.types.WindowManager.leap_status = bpy.props.StringProperty(default="Stopped", options={'SKIP_SAVE'})
    bpy.utils.register_class(LEAP_PT_Panel)


def unregister():
    bpy.utils.unregister_class(LEAP_PT_Panel)
    for name in ("leap_port", "leap_target_rig", "leap_scale"):
        delattr(bpy.types.Scene, name)
    for name in ("leap_listening", "leap_status"):
        delattr(bpy.types.WindowManager, name)

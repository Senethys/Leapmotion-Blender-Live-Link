bl_info = {
    "name": "Leap Motion Live Link",
    "author": "fnoji",
    "version": (1, 1, 0),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Leap Link",
    "description": "Live link for Ultraleap Leap Motion",
    "category": "Animation",
}

from . import panel, operator

def register():
    panel.register()
    operator.register()

def unregister():
    operator.unregister()
    panel.unregister()

if __name__ == "__main__":
    register()

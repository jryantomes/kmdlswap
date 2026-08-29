"""Run inside Blender (headless) to inspect an FBX, or convert one mesh to OBJ.

The brief scopes FBX as "only if trivial", and parsing it directly is not. But
Blender already reads it, so it is used purely as a converter - kmdlswap itself
still only ever ingests OBJ.

Inspect:
    blender --background --python tools/blender_fbx.py -- --fbx in.fbx

Convert one object:
    blender --background --python tools/blender_fbx.py -- \
        --fbx in.fbx --object Head --out head.obj

Coordinates are exported with no axis conversion (axis_forward='Y', axis_up='Z'),
because KOTOR is Z-up and kmdlswap writes and reads OBJ verbatim. Anything else
would silently rotate the mesh.
"""

import json
import sys

import bpy


def argv_after_dashes():
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_args(args):
    out = {}
    key = None
    for a in args:
        if a.startswith("--"):
            key = a[2:]
            out[key] = True
        elif key:
            out[key] = a
            key = None
    return out


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def main():
    args = parse_args(argv_after_dashes())
    fbx = args.get("fbx")
    if not fbx:
        print("RESULT " + json.dumps({"error": "no --fbx given"}))
        return

    clear_scene()
    bpy.ops.import_scene.fbx(filepath=fbx)

    meshes = []
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        me = obj.data
        me.calc_loop_triangles()
        uv_layers = [layer.name for layer in me.uv_layers]
        meshes.append(
            {
                "object": obj.name,
                "mesh": me.name,
                "vertices": len(me.vertices),
                "triangles": len(me.loop_triangles),
                "uv_layers": uv_layers,
                "vertex_groups": [g.name for g in obj.vertex_groups],
                "parent": obj.parent.name if obj.parent else None,
                "scale": list(obj.scale),
                "location": list(obj.location),
                "dimensions": list(obj.dimensions),
            }
        )

    summary = {
        "file": fbx,
        "objects_total": len(bpy.data.objects),
        "armatures": [o.name for o in bpy.data.objects if o.type == "ARMATURE"],
        "actions": len(bpy.data.actions),
        "meshes": meshes,
    }

    target = args.get("object")
    out = args.get("out")
    if target and out:
        obj = bpy.data.objects.get(target)
        if obj is None or obj.type != "MESH":
            summary["error"] = f"no mesh object named {target!r}"
        else:
            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            # KOTOR stores each node's geometry in NODE-LOCAL space; the node's
            # own position and orientation live in the node header, which
            # kmdlswap never touches. Blender's OBJ exporter writes world space,
            # which would bake in the whole parent chain and put the mesh in the
            # wrong place. Reduce the object's transform to its own scale only:
            # translation and rotation drop out, while the scale-100 that FBX
            # puts on skinned meshes is preserved.
            from mathutils import Matrix

            sx, sy, sz = obj.scale
            obj.matrix_world = Matrix.Diagonal((sx, sy, sz, 1.0))
            bpy.context.view_layer.update()
            summary["export_scale_applied"] = [sx, sy, sz]
            bpy.ops.export_scene.obj(
                filepath=out,
                use_selection=True,
                use_mesh_modifiers=True,
                use_normals=True,
                use_uvs=True,
                use_materials=False,
                use_triangles=True,
                axis_forward="Y",
                axis_up="Z",
                global_scale=1.0,
            )
            summary["exported"] = out

    print("RESULT " + json.dumps(summary))


main()

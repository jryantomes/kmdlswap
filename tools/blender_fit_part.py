"""Run inside Blender (headless): carve one body part out of a foreign rigged
mesh, decimate it to a KOTOR-sized budget, fit it to a target node's extents,
and write an OBJ.

This is the *fitting* step, and it is deliberately NOT part of kmdlswap. The
brief scopes that tool to swapping one node's geometry; deciding how a foreign
mesh should be cut up, simplified and positioned is authoring work that belongs
in a 3D application. This script just automates it for testing.

    blender --background --python tools/blender_fit_part.py -- \
        --fbx in.fbx --vgroup mixamorig:Head --tris 393 \
        --fit-x 0.300 --fit-y 0.333 --fit-z 0.266 --out head.obj
"""

import json
import sys

import bpy


def argv_after_dashes():
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def parse_args(args):
    out, key = {}, None
    for a in args:
        if a.startswith("--"):
            key = a[2:]
            out[key] = True
        elif key:
            out[key] = a
            key = None
    return out


def main():
    a = parse_args(argv_after_dashes())
    result = {}

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=a["fbx"])

    obj = next((o for o in bpy.data.objects if o.type == "MESH"), None)
    if obj is None:
        print("RESULT " + json.dumps({"error": "no mesh in FBX"}))
        return
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Bake the object's transform (FBX puts scale 100 on skinned meshes) so the
    # mesh data itself is in real units before anything is measured.
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    result["source"] = {
        "object": obj.name,
        "vertices": len(obj.data.vertices),
        "dimensions": list(obj.dimensions),
    }

    # --- carve out the requested vertex group
    vgroup = a.get("vgroup")
    if vgroup:
        if vgroup not in obj.vertex_groups:
            print("RESULT " + json.dumps({"error": f"no vertex group {vgroup!r}"}))
            return
        obj.vertex_groups.active = obj.vertex_groups[vgroup]
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.vertex_group_select()
        bpy.ops.mesh.select_all(action="INVERT")
        bpy.ops.mesh.delete(type="VERT")
        bpy.ops.object.mode_set(mode="OBJECT")
        result["after_carve"] = {"vertices": len(obj.data.vertices)}
        if not len(obj.data.vertices):
            print("RESULT " + json.dumps({"error": f"{vgroup!r} selected nothing"}))
            return

    obj.data.calc_loop_triangles()
    before_tris = len(obj.data.loop_triangles)

    # --- decimate to the triangle budget
    target = int(a.get("tris", 400))
    if before_tris > target:
        mod = obj.modifiers.new("dec", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = max(target / before_tris, 0.0001)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.data.calc_loop_triangles()
    result["decimated"] = {
        "from_triangles": before_tris,
        "to_triangles": len(obj.data.loop_triangles),
        "vertices": len(obj.data.vertices),
    }

    # --- centre on origin and fit to the target node's extents
    coords = [v.co.copy() for v in obj.data.vertices]
    lo = [min(c[i] for c in coords) for i in range(3)]
    hi = [max(c[i] for c in coords) for i in range(3)]
    centre = [(lo[i] + hi[i]) / 2 for i in range(3)]
    size = [hi[i] - lo[i] for i in range(3)]

    fit = [a.get("fit-x"), a.get("fit-y"), a.get("fit-z")]
    if all(fit):
        fit = [float(x) for x in fit]
        # Uniform scale, so the part is not distorted: use the tightest axis.
        factor = min(fit[i] / size[i] for i in range(3) if size[i] > 1e-9)
    else:
        factor = 1.0

    # Where the replacement should sit in node-local space. A node's geometry is
    # not necessarily centred on its own origin - HK-47's head sits +0.078 above
    # it - so dropping a part at (0,0,0) leaves it visibly low.
    target_centre = [float(a.get(f"centre-{ax}", 0.0)) for ax in ("x", "y", "z")]

    for v in obj.data.vertices:
        for i in range(3):
            v.co[i] = (v.co[i] - centre[i]) * factor + target_centre[i]

    coords = [v.co for v in obj.data.vertices]
    result["fitted"] = {
        "scale_factor": factor,
        "target_centre": target_centre,
        "size_before": size,
        "size_after": [
            max(c[i] for c in coords) - min(c[i] for c in coords) for i in range(3)
        ],
    }

    # The OBJ exporter writes WORLD space. This mesh is parented to the armature,
    # so transform_apply cleared only its own matrix - the parent's offset would
    # still be baked in, landing the part far from the node's local origin.
    # Detach it and force an identity world matrix so the exported coordinates
    # are exactly the centred mesh data.
    from mathutils import Matrix

    # The exporter evaluates modifiers, and this mesh still carries an Armature
    # modifier - leaving it on would export the mesh DEFORMED BY THE POSE, which
    # both rotates and displaces it. Strip every modifier, detach from the
    # armature, and force an identity world matrix so the exported coordinates
    # are exactly the centred mesh data.
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    obj.parent = None
    obj.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    result["modifiers_after"] = [m.name for m in obj.modifiers]

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.obj(
        filepath=a["out"],
        use_selection=True,
        use_normals=True,
        use_uvs=True,
        use_materials=False,
        use_triangles=True,
        axis_forward="Y",
        axis_up="Z",
        global_scale=1.0,
    )
    result["exported"] = a["out"]
    print("RESULT " + json.dumps(result))


main()

"""Run inside Blender (headless): render a manifest of OBJs to PNGs.

One Blender process renders the whole batch, because starting Blender costs
several seconds and there are 164 models.

Flat grey, orthographic, front view. No textures and no materials on purpose:
the question these previews answer is *what shape is this and how big is it*,
and colour would only distract from silhouette and proportion. Orthographic with
a shared scale across a batch means two models can be compared directly.

KOTOR characters face +Y, so the camera sits on +Y looking towards -Y.

This was wrong until the in-app previewer gained textures: the earlier reading
of "largest front-back asymmetry on Y, negative" had the sign backwards, and an
untextured low-poly head looks equally plausible from either side, so nothing
contradicted it. Settled two ways - four textured models show a face only from
+Y, and every eye, teeth and tongue node in a vanilla head sits at positive Y.
Catalogue images rendered before this fix show the backs of characters' heads.

    blender --background --python tools/blender_render.py -- --manifest jobs.json
"""

import json
import math
import sys

import bpy
from mathutils import Vector


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


def setup_world(width: int, height: int):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.eevee.taa_render_samples = 16

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("cam", cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    key = bpy.data.lights.new("key", type="SUN")
    key.energy = 3.0
    key_obj = bpy.data.objects.new("key", key)
    key_obj.rotation_euler = (math.radians(55), 0.0, math.radians(-35))
    scene.collection.objects.link(key_obj)

    fill = bpy.data.lights.new("fill", type="SUN")
    fill.energy = 1.2
    fill_obj = bpy.data.objects.new("fill", fill)
    fill_obj.rotation_euler = (math.radians(70), 0.0, math.radians(140))
    scene.collection.objects.link(fill_obj)

    mat = bpy.data.materials.new("clay")
    mat.diffuse_color = (0.72, 0.72, 0.74, 1.0)
    return cam, mat


def clear_meshes():
    for obj in list(bpy.data.objects):
        if obj.type == "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def frame(cam, objects, margin: float = 1.12):
    """Point an orthographic camera at the objects from +Y, where the face is."""
    corners = []
    for obj in objects:
        for c in obj.bound_box:
            corners.append(obj.matrix_world @ Vector(c))
    if not corners:
        return None
    lo = Vector((min(c[i] for c in corners) for i in range(3)))
    hi = Vector((max(c[i] for c in corners) for i in range(3)))
    centre = (lo + hi) / 2
    size = hi - lo

    cam.data.ortho_scale = max(size.x, size.z, 1e-4) * margin
    depth = max(size.y, 1.0) * 4 + 2
    cam.location = (centre.x, centre.y + depth, centre.z)
    # Look along +Y with Z up.
    cam.rotation_euler = (math.radians(90), 0.0, math.radians(180))
    return size


def main():
    a = parse_args(argv_after_dashes())
    jobs = json.loads(open(a["manifest"], encoding="utf-8").read())
    width = int(a.get("width", 320))
    height = int(a.get("height", 480))

    cam, mat = setup_world(width, height)
    done, failed = 0, []
    for job in jobs:
        clear_meshes()
        try:
            bpy.ops.import_scene.obj(filepath=job["obj"], axis_forward="Y", axis_up="Z")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{job['name']}: import: {exc}")
            continue
        meshes = [o for o in bpy.data.objects if o.type == "MESH"]
        if not meshes:
            failed.append(f"{job['name']}: no meshes")
            continue
        for obj in meshes:
            obj.data.materials.clear()
            obj.data.materials.append(mat)
            for poly in obj.data.polygons:
                poly.use_smooth = False
        if frame(cam, meshes) is None:
            failed.append(f"{job['name']}: empty bounds")
            continue
        bpy.context.scene.render.filepath = job["png"]
        bpy.ops.render.render(write_still=True)
        done += 1
        if done % 25 == 0:
            print(f"PROGRESS {done}/{len(jobs)}", flush=True)

    print("RESULT " + json.dumps({"rendered": done, "failed": failed[:20]}))


main()

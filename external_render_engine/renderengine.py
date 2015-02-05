# This file is part of external_render_engine.  external_render_engine is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright David Bernard

import bpy
import bgl
import asyncio
from . import protocol     # pylint: disable=W0406
from . import helpers      # pylint: disable=W0406
from . import pgex_export  # pylint: disable=W0406

# gloop = external_render_engine.gloop

# http://wiki.blender.org/index.php/Dev:2.6/Source/Render/RenderEngineAPI
# http://wiki.blender.org/index.php/Dev:2.6/Source/Render/UpdateAPI
# http://www.blender.org/api/blender_python_api_2_72_release/bpy.types.RenderEngine.html


class SceneChangeListener:

    def __init__(self, ctx):
        self.ctx = ctx
        self.first = True

    def register(self):
        print("register SceneChangeListener")
        bpy.app.handlers.scene_update_post.append(self.scene_update_post)

    def unregister(self):
        print("unregister SceneChangeListener")
        # bpy.app.handlers.scene_update_pre.remove(self.scene_update_pre)
        bpy.app.handlers.scene_update_post.remove(self.scene_update_post)

    def scene_update_post(self, scene):
        # print("scene_update_post")
        for obj in scene.objects:
            if obj.is_updated or self.first:
                self.ctx.need_update(obj, True)
            if (obj.data is not None) and (obj.is_updated_data or self.first):
                self.ctx.need_update(obj.data, True)
            if obj.type == 'MESH':
                for i in range(len(obj.material_slots)):
                    src_mat = obj.material_slots[i].material
                    if src_mat.is_updated or self.first:
                        self.ctx.need_update(src_mat, True)
        self.first = False

class ExternalRenderEngine(bpy.types.RenderEngine):
    # These three members are used by blender to set up the
    # RenderEngine; define its internal name, visible name and capabilities.
    bl_idname = "EXTERNAL_RENDER"
    bl_label = "External Render"
    bl_use_preview = False
    is_animation = True

    # moved assignment from execute() to the body of the class...

    def __init__(self):
        print("__init__")
        self.host = "127.0.0.1"
        self.port = 4242
        self.client = protocol.Client()
        self.sceneChangeListener = None

    def __del__(self):
        print("__del__")
        if hasattr(self, 'client'):
            self.client.close()
        if hasattr(self, 'client') and self.sceneChangeListener is not None:
            self.sceneChangeListener.unregister()

    def external_render(self, context_or_camera, width, height, flocal):
        (loc, rot, projection, near, far) = helpers.extractEye(context_or_camera)

        @asyncio.coroutine
        def my_render():
            try:
                self.report({'WARNING'}, "test remote host (%r:%r)" % (self.host, self.port))
                yield from self.client.connect(self.host, self.port)
                # print('Send: %rx%r' % (width, height))
                protocol.setEye(self.client.writer, loc, rot, projection, near, far)
                protocol.askScreenshot(self.client.writer, width, height)
                # yield from writer.drain()

                (kind, raw) = yield from protocol.readMessage(self.client.reader)
                # raw = [[128, 255, 0, 255]] * (width * height)
                if kind == protocol.Kind.raw_screenshot:
                    flocal(width, height, raw)
            except BrokenPipeError:
                self.report({'WARNING'}, "failed to connect to remote host (%r:%r)" % (self.host, self.port))
                self.client.close()
        protocol.run_until_complete(my_render())

    def render(self, scene):
        scale = scene.render.resolution_percentage / 100.0
        width = int(scene.render.resolution_x * scale)
        height = int(scene.render.resolution_y * scale)
        # context.space_data.camera
        # self.external_render(scene.camera, width, height, self.render_image)

    def update(self, data, scene):
        """Export scene data for render"""
        self.report({'DEBUG'}, "update")
        self.external_update(scene)

    def view_update(self, context):
        self.report({'DEBUG'}, "view_update")
        self.external_update(context.scene)

    def external_update(self, scene):
        self.report({'DEBUG'}, "external_update")
        self.host = scene.external_render.host
        self.port = scene.external_render.port
        cfg = pgex_export.ExportCfg(is_preview=False, assets_path=scene.pgex.assets_path)

        # for ob in scene.objects:
        #     if ob.is_updated:
        #         print("updated =>", ob.name)

        @asyncio.coroutine
        def my_update():
            try:
                yield from self.client.connect(self.host, self.port)
                protocol.changeAssetFolders(self.client.writer, cfg)
                protocol.setData(self.client.writer, scene, cfg)
            except BrokenPipeError:
                self.report({'WARNING'}, "failed to connect to remote host (%r:%r)" % (self.host, self.port))
                self.client.close()

        if self.sceneChangeListener is None:
            self.sceneChangeListener = SceneChangeListener(cfg)
            self.sceneChangeListener.register()
            self.sceneChangeListener.scene_update_post(scene)
        protocol.run_until_complete(my_update())
        # else:
        #     if len(self.sceneChangeListener.updated) > 0:
        #         cfg.objects_included.extend(self.sceneChangeListener.updated)
        #         for ob in self.sceneChangeListener.updated:
        #             print("updated =>", ob.name)
        #         self.sceneChangeListener.updated.clear()
        #         protocol.run_until_complete(my_update())
        #     for ob in self.sceneChangeListener.deleted:
        #         print("deleted =>", ob)

    def view_draw(self, context):
        self.report({'DEBUG'}, "view_draw")
        # self.view_update(context)
        # from http://blender.stackexchange.com/questions/5035/moving-user-perspective-in-blender-with-python
        # area = context.area
        # area = context.screen.areas[2]
        # r3d = area.spaces[0].region_3d # region_3d of 3D View
        # for area in bpy.context.screen.areas:
        # if area.type=='VIEW_3D':
        #         break
        #
        # space = area.spaces[0]
        # region = area.regions[4]
        # rv3d = context.space_data.region_3d
        # loc = r3d.view_matrix.col[3][1:4]  # translation part of the view matrix
        region = context.region  # area.regions[4]
        width = int(region.width)
        height = int(region.height)
        self.external_render(context, width, height, self.view_draw_image)

    def render_image(self, width, height, raw):
        # TODO optimize the loading/convertion of raw (other renderegine use load_from_file instead of rect)
        # do benchmark array vs list
        # convert raw (1D,brga, byte) into rect (2D, rgba, float [0,1])

        # data = list()
        # for p in range(width * height):
        #     i = p * 4
        #     data.append([float(raw[i + 2])/255.0, float(raw[i + 1])/255.0, float(raw[i + 0])/255.0, float(raw[i + 3])/255.0])
        #     # data.append([float(raw[i + 0]), float(raw[i + 1]), float(raw[i + 2]), float(raw[i + 3])]) # crash
        #
        # # data = [[float(raw[i + 2])/255.0, float(raw[i + 1])/255.0, float(raw[i + 0])/255.0, float(raw[i + 3])/255.0] for p in range(width * height) i = p * 4]
        # pylint: disable=E1103
        import numpy
        # print("w * h : %r   len/4 : %s" % (width*height, len(raw)/4))
        data = numpy.fromstring(raw, dtype=numpy.byte).astype(numpy.float)
        data = numpy.reshape(data, (len(raw)/4, 4))
        reorder = numpy.array([2, 1, 0, 3])
        data = data[:, reorder]
        divfunc = numpy.vectorize(lambda a: a / 255.0)
        data = divfunc(data)
        # pylint: enable=E1103

        result = self.begin_result(0, 0, width, height)
        layer = result.layers[0]
        layer.rect = data
        self.end_result(result)

    def view_draw_image(self, width, height, raw):
        # raw = [[0, 255, 0, 255]] * (width * height)
        pixel_count = width * height
        bitmap = bgl.Buffer(bgl.GL_BYTE, [pixel_count * 4], raw)
        # bgl.glBitmap(self.size_x, self.size_y, 0, 0, 0, 0, bitmap)
        bgl.glRasterPos2i(0, 0)
        bgl.glDrawPixels(width, height,
                         # Blender.BGL.GL_BGRA, Blender.BGL.GL_UNSIGNED_BYTE,
                         0x80E1, 0x1401,
                         # bgl.GL_BGRA, bgl.GL_UNSIGNED_BYTE,
                         bitmap
                         )

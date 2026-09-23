"""The resample heads-up display: the counts on the paths, and the keys along the bottom.

Two things anchor the numbers, and they pull in opposite directions.  The number has to
sit where the user's selection is, which is a point in the 3D view, so the view matrices
have to be walked by hand -- Blender exposes no world-to-pixel helper for a viewport that
is not a camera.  Where it sits, though, comes from the curve the step was built on rather
than from the rebuilt mesh: that mesh has a different vertex count every scroll, and a
label measured off it would hop along with the points being added and removed, which reads
as the mesh flickering while the scroll settles.  A path's own halfway point is one value
that survives a rebuild, so the operator hands it over once per step.

The number is segments, not points, because a resampled ring is described by how many
pieces it was cut into -- that is the number on the wire, and the one the user counts.
See ``segment_counts`` for why it is one less than the planner's point count.

The row of chips along the bottom is yl_bevelflow's, and it stays what his is: a readout,
not a control.  Nothing here is clickable, because the wheel already is the control; what the
row carries is which axis the wheel is pointed at, and how far along it the standing mesh
sits at.  The second of those is now a percentage rather than a pole word: a tick raises one
function further instead of choosing between two, so the reading is a value the wheel
actually chose.  It gains his row's
other job too: when the planner refuses a step, the reason lands in the row as a warning chip,
because a scroll that does nothing and says nothing reads as a dead wheel.
"""

import blf
import gpu
import math

import bmesh
from collections import OrderedDict
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from ..shape.state import (
    MODE_COUNT,
    MODE_EVEN,
    MODE_SMOOTH,
)


_FONT_ID = 0
_FONT_PIXELS = 22
# blf.shadow takes a level out of (0, 3, 5, 6) and raises on anything else.
_SHADOW_LEVEL = 3
# The counts sit on the mesh, so they are bright yellow with a dark halo behind them:
# yellow alone washes out against a pale shading or a pale material, and a bright-on-bright
# shadow would make them vanish altogether.
_NUMBER_COLOR = (1.0, 0.95, 0.1, 1.0)
_SHADOW_COLOR = (0.05, 0.05, 0.05, 0.85)

# The adjusted paths, traced over the mesh they are being rebuilt on.  Two colours
# because two things are being said: the *edge* is what got resampled, so it is fluorescent
# green and reads as a line, and the *point* on it is the number printed above it, so the
# dot is the same bright yellow as that number and reads as a node.  yl_meshcheckhud's
# technique, worth borrowing whole: one POST_VIEW handler, the POLYLINE_UNIFORM_COLOR
# builtin, and a batch of world-space segments.
_HIGHLIGHT_COLOR = (0.2, 1.0, 0.2, 1.0)
_HIGHLIGHT_POINT_COLOR = (1.0, 0.95, 0.1, 1.0)
_HIGHLIGHT_WIDTH = 2.5
_HIGHLIGHT_POINT_SIZE = 6.0
# The overlay lies exactly on the surface it is marking, so it has to be nudged toward the
# eye to win the depth test at all.  A dot is a disk of pixels, and half of them land on
# mesh that bulges closer to the camera than the point itself does -- that, and nothing
# else, is what cut the dots in half.  The nudge travels along the ray to the eye, so it
# changes the depth and touches nothing else: the pixels a dot covers are the pixels it
# would have covered anyway, which a nudge along the surface or along the normal is not.
# It is a fraction of the distance rather than a fixed length, so it holds up whether the
# mesh is a detail pass or a building, and at any distance the camera sits.
_HIGHLIGHT_LIFT = 0.002
_HIGHLIGHT = {
    "points": (),
    "segments": (),
    "batches": None,
    "geometry_key": None,
    "view": None,
}

_CHIP_FONT_PIXELS = 18
_CHIP_BOTTOM_MARGIN = 80.0
# The failure notice is the planner's own sentence, with the operator-wide "failed safely"
# wrapper taken off: the overlay is the only screen the user is looking at, and the
# wrapper just repeats that there is a notice.  A reason longer than a viewport is wide
# gets its tail cut, because the cause is always in the front half of the sentence.
_FAILURE_PREFIX = "Loop Resample failed safely: "
_FAILURE_LIMIT = 96
# The chip row is yl_bevelflow's, measure for measure: his buttons are laid out at a
# fixed 1.3 * 0.96 spacing scale, the text is lifted off its padding by hand, and the
# outline is one pixel wide whatever the interface scale says.
_CHIP_BUTTON_SCALE = 0.96
_CHIP_UI_SCALE = 1.3 * _CHIP_BUTTON_SCALE
_CHIP_PADDING_X = 9.0
_CHIP_PADDING_Y = 5.0
_CHIP_GAP = 4.0
_CHIP_TEXT_LIFT = 3.0
_CHIP_RADIUS = 8.0
_CHIP_STYLES = {
    "active": (
        (0.25, 0.25, 0.25, 0.90),
        (0.35, 0.35, 0.35, 0.95),
        (1.0, 0.2, 0.32, 1.0),
    ),
    "warning": (
        (0.40, 0.12, 0.12, 0.88),
        (0.68, 0.22, 0.22, 0.95),
        (1.0, 0.82, 0.82, 1.0),
    ),
    "hotkey_active": (
        (0.15, 0.32, 0.42, 0.88),
        (0.24, 0.52, 0.68, 0.95),
        (0.2, 0.9, 1.0, 1.0),
    ),
    "hotkey": (
        (0.20, 0.20, 0.20, 0.75),
        (0.35, 0.35, 0.35, 0.90),
        (0.7, 0.7, 0.7, 1.0),
    ),
    "label": (
        (0.20, 0.20, 0.20, 0.75),
        (0.35, 0.35, 0.35, 0.90),
        (0.9, 0.9, 0.9, 1.0),
    ),
}

_SHADER = None
_HIGHLIGHT_SHADER = None
_HIGHLIGHT_POINT_SHADER = None
_BOX_CACHE = OrderedDict()
_BOX_CACHE_LIMIT = 48


def path_midpoint(points, closed):
    """The point half the path's own length along from its first vertex.

    Local coordinates, straight off the frozen source, so this is a position in the mesh
    rather than on the screen.  For a closed loop "halfway" is measured from whichever
    vertex the sampler started on, which is as good a spot as any and never moves.
    """
    if not points:
        return None
    ring = [Vector(point) for point in points]
    if closed:
        ring.append(ring[0])
    if len(ring) < 2:
        return ring[0]
    lengths = [
        (ring[index + 1] - ring[index]).length for index in range(len(ring) - 1)
    ]
    total = sum(lengths)
    if total <= 1e-9:
        return ring[0]
    target = total * 0.5
    walked = 0.0
    for index, length in enumerate(lengths):
        if walked + length < target:
            walked += length
            continue
        if length <= 1e-9:
            return ring[index]
        factor = (target - walked) / length
        return ring[index].lerp(ring[index + 1], factor)
    return ring[-1]


def segment_counts(point_counts, closed_flags):
    """A path's point count as the segment count the user counts on the wire.

    The planner thinks in points -- how many samples it has to place -- and the user thinks
    in segments, because that is what a resampled edge ring is built out of.  The two are
    not one apart in general: an open path of ``n`` points has ``n - 1`` edges between
    them, while a closed loop of ``n`` points has ``n`` edges, its last one closing it
    back onto its first point.  So only the open path loses one.

    It is recomputed per label rather than stored, so the stored numbers stay the numbers
    the planner takes: one source of truth for a count, translated once, at the moment it
    is drawn or reported.
    """
    return tuple(
        points if closed else points - 1
        for points, closed in zip(point_counts, closed_flags)
    )


def _failure_text(message):
    """A planner failure as the sentence that fits in a chip."""
    if message is None:
        return ""
    text = str(message)
    if text.startswith(_FAILURE_PREFIX):
        text = text[len(_FAILURE_PREFIX) :]
    text = " ".join(text.split())
    if len(text) > _FAILURE_LIMIT:
        text = text[: _FAILURE_LIMIT - 3].rstrip() + "..."
    return text


def _window_region(area):
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return None


def _to_pixels(region, view_projection, world_point):
    """A 3D point in world space as pixels inside the viewport region.

    ``perspective_matrix`` already folds the view transform and the region's window
    transform together.  The point has to be handed over as a homogeneous 4-vector: a
    3-vector in is multiplied as three rows and comes back three-wide with ``w`` silently
    dropped, which leaves nothing to divide by.
    """
    clip = view_projection @ Vector((*world_point, 1.0))
    if clip.w <= 1e-9:
        return None
    return (
        (clip.x / clip.w * 0.5 + 0.5) * region.width,
        (clip.y / clip.w * 0.5 + 0.5) * region.height,
    )


def _uniform_color_shader():
    global _SHADER
    if _SHADER is None:
        _SHADER = gpu.shader.from_builtin("UNIFORM_COLOR")
    return _SHADER


def _polyline_shader():
    global _HIGHLIGHT_SHADER
    if _HIGHLIGHT_SHADER is None:
        _HIGHLIGHT_SHADER = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    return _HIGHLIGHT_SHADER


def _point_shader():
    """The round, soft-edged dot yl_meshcheckhud draws its problem vertices with.

    The built-in point shader would do, but it squares off at the edges and takes no
    antialiasing, and a row of those reads as a dashed ruler rather than a set of points.
    """
    global _HIGHLIGHT_POINT_SHADER
    if _HIGHLIGHT_POINT_SHADER is None:
        shader_info = gpu.types.GPUShaderCreateInfo()
        shader_info.push_constant('MAT4', "ModelViewProjectionMatrix")
        shader_info.push_constant('VEC4', "color")
        shader_info.push_constant('FLOAT', "size")
        shader_info.vertex_in(0, 'VEC3', "pos")
        shader_info.fragment_out(0, 'VEC4', "fragColor")
        shader_info.vertex_source(
            "void main()"
            "{"
            "  gl_Position = ModelViewProjectionMatrix * vec4(pos, 1.0);"
            "  gl_PointSize = size;"
            "}"
        )
        shader_info.fragment_source(
            "void main()"
            "{"
            "  vec2 centered = (gl_PointCoord * 2.0) - vec2(1.0);"
            "  float radius_sq = dot(centered, centered);"
            "  if (radius_sq > 1.0) discard;"
            "  float edge = smoothstep(1.0, 0.7, radius_sq);"
            "  fragColor = vec4(color.rgb, color.a * edge);"
            "}"
        )
        _HIGHLIGHT_POINT_SHADER = gpu.shader.create_from_info(shader_info)
        del shader_info
    return _HIGHLIGHT_POINT_SHADER


def _rounded_box_geometry(width, height, radius, border_width, resolution=12):
    """Corner arcs and triangle indices for a rounded rectangle, keyed by a rounded size.

    Taken from yl_bevelflow's HUD.  The key quantises the size so a chip that changes
    width by a pixel when the count gains a digit keeps the batch it already built.
    """
    key = (
        int(float(width) // 5) * 5,
        int(float(height) // 2) * 2,
        round(float(radius), 3),
        round(float(border_width), 3),
        int(resolution),
    )
    cached = _BOX_CACHE.get(key)
    if cached is not None:
        _BOX_CACHE.move_to_end(key)
        return cached

    centers = (
        (width - radius, height - radius),
        (radius, height - radius),
        (radius, radius),
        (width - radius, radius),
    )
    outer_verts = []
    inner_verts = []
    inner_radius = max(0.1, radius - border_width)
    for corner, (center_x, center_y) in enumerate(centers):
        start_angle = corner * (math.pi / 2)
        for step in range(resolution + 1):
            theta = start_angle + (math.pi / 2) * (step / resolution)
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)
            outer_verts.append((center_x + cos_t * radius, center_y + sin_t * radius))
            inner_verts.append(
                (center_x + cos_t * inner_radius, center_y + sin_t * inner_radius)
            )

    inner_count = len(inner_verts)
    background_indices = []
    for index in range(inner_count):
        first = index + 1
        second = (index + 1) % inner_count + 1
        background_indices.append((0, first, second))

    border_indices = []
    for index in range(inner_count):
        outer_first = index
        outer_second = (index + 1) % inner_count
        inner_first = index + inner_count
        inner_second = (index + 1) % inner_count + inner_count
        border_indices.extend(
            [(outer_first, inner_first, outer_second), (inner_first, inner_second, outer_second)]
        )

    cached = (
        tuple(outer_verts),
        tuple(inner_verts),
        tuple(background_indices),
        tuple(border_indices),
    )
    _BOX_CACHE[key] = cached
    while len(_BOX_CACHE) > _BOX_CACHE_LIMIT:
        _BOX_CACHE.popitem(last=False)
    return cached


def _draw_rounded_box(x, y, width, height, background, border, radius, border_width):
    """A filled rounded rectangle with an outline, in region pixels from the bottom left."""
    radius = min(radius, min(width, height) / 2)
    outer_rel, inner_rel, background_indices, border_indices = _rounded_box_geometry(
        width, height, radius, border_width
    )
    shader = _uniform_color_shader()
    shader.bind()
    gpu.state.blend_set("ALPHA")

    background_verts = [(x + width / 2, y + height / 2)] + [
        (x + offset_x, y + offset_y) for offset_x, offset_y in inner_rel
    ]
    batch = batch_for_shader(
        shader, "TRIS", {"pos": background_verts}, indices=background_indices
    )
    shader.uniform_float("color", background)
    batch.draw(shader)

    border_verts = [(x + offset_x, y + offset_y) for offset_x, offset_y in outer_rel]
    border_verts += [(x + offset_x, y + offset_y) for offset_x, offset_y in inner_rel]
    batch = batch_for_shader(
        shader, "TRIS", {"pos": border_verts}, indices=border_indices
    )
    shader.uniform_float("color", border)
    batch.draw(shader)
    gpu.state.blend_set("NONE")


def _chips(operator):
    """The three axes and the two clicks, as the typed parts yl_bevelflow's chip row takes.

    Every axis names the key that claims the wheel, armed or not, so the row reads as a
    list of what drives what and the lit one is where the next tick lands.  Under a held
    modifier that lit chip is also the only confirmation on screen that the key was heard at
    all: the wheel is doing something other than what it does by default, and nothing on the
    mesh says why.

    The strengths are the ones that reached a mesh rather than the ones the wheel was last
    turned to, which is the same rule the count already follows: a refused step leaves the
    previous mesh standing, and a chip that moved anyway would be describing a mesh that is
    not there.
    """
    closed = operator.label_closed
    entry = ", ".join(
        str(value) for value in segment_counts(operator.entry_counts, closed)
    )
    current = ", ".join(
        str(value) for value in segment_counts(operator.label_values, closed)
    )
    mode = getattr(operator, "mode", MODE_COUNT)
    return (
        {
            "text": "[Wheel] Segments " + entry + " → now " + current,
            "type": "hotkey_active" if mode == MODE_COUNT else "active",
        },
        {
            "text": "[Shift] Smooth" + _strength_text(operator, "label_smooth"),
            "type": "hotkey_active" if mode == MODE_SMOOTH else "hotkey",
        },
        {
            "text": "[Ctrl] Even" + _strength_text(operator, "label_even"),
            "type": "hotkey_active" if mode == MODE_EVEN else "hotkey",
        },
        # One button, mouse only: this is a scroll interaction, and the keyboard version
        # of keep and revert would need keys Blender has already handed to other tools.
        {"text": "[LMB] Keep   [RMB] Revert", "type": "hotkey"},
    )


def _strength_text(operator, attribute):
    """How far along its one axis the standing mesh sits, or nothing at the source.

    Zero is the source curve, the one position on these axes with no strength to read,
    so it leaves the chip bare rather than showing a neutral reading of its own.  Past
    it the chip reads a percentage, because that is what a scroll now chose: an axis
    with one function is only ever raised further, so the number is the wheel's own
    reading rather than a stand-in for a direction.
    """
    value = getattr(operator, attribute, 0.0)
    if value == 0.0:
        return ""
    return " " + str(int(round(value * 100))) + "%"


def _draw_chip(chip, x, bottom, width, box_height, padding_x, padding_y, text_lift, scale):
    """One chip: yl_bevelflow's rounded box, his outline width, his text placement."""
    background, outline, text_color = _CHIP_STYLES.get(
        chip.get("type"), _CHIP_STYLES["label"]
    )
    _draw_rounded_box(
        x,
        bottom,
        width,
        box_height,
        background,
        outline,
        _CHIP_RADIUS * scale,
        1.0,
    )
    blf.color(_FONT_ID, *text_color)
    blf.position(_FONT_ID, x + padding_x, bottom + padding_y + text_lift, 0.0)
    blf.draw(_FONT_ID, chip["text"])


def _chip_metrics(chips, scale, text_size=None):
    """Widths, height and total run of a row of chips, in region pixels.

    ``text_size`` is let through because both the row and the failure notice have to fit
    the region they are drawn in, and the only way to know that is to measure at a size and
    try a smaller one: the notice because it is a sentence rather than a label, and the row
    because four labelled chips are a wider thing than two were.
    """
    ui_scale = _CHIP_UI_SCALE * scale
    padding_x = _CHIP_PADDING_X * ui_scale
    padding_y = _CHIP_PADDING_Y * ui_scale
    item_gap = _CHIP_GAP * ui_scale
    if text_size is None:
        text_size = max(10, int(_CHIP_FONT_PIXELS * scale))
    blf.size(_FONT_ID, text_size)
    widths = []
    tallest = 0
    total = 0.0
    for chip in chips:
        width, height = blf.dimensions(_FONT_ID, chip["text"])
        widths.append(width + padding_x * 2)
        tallest = max(tallest, height)
        total += width + padding_x * 2
    total += (len(chips) - 1) * item_gap
    return {
        "widths": widths,
        "padding_x": padding_x,
        "padding_y": padding_y,
        "item_gap": item_gap,
        "text_lift": _CHIP_TEXT_LIFT * ui_scale,
        "height": tallest + padding_y * 2,
        "total": total,
    }


def _draw_failure_chip(operator, region, scale, above):
    """The planner's refusal, as a warning chip of its own above the row.

    Not one more chip in the row: a planner sentence is longer than every label in it put
    together, and adding it would push keep and revert off the sides of the viewport.  On
    a row of its own, centred and in the warning red, it reads as a notice about the step
    that was just tried rather than one more thing to press.  Silence would be the other
    option -- the wheel does nothing, after all -- but a wheel that does nothing and says
    nothing is indistinguishable from a wheel the operator is not listening to.
    """
    message = _failure_text(getattr(operator, "message", None))
    if not message:
        return
    chip = {"text": message, "type": "warning"}
    text_size = max(10, int(_CHIP_FONT_PIXELS * scale))
    metrics = _chip_metrics((chip,), scale, text_size)
    # One pixel at a time, and only down to the same floor the row uses: a reason nobody
    # can read is no reason at all, but a reason wider than the window is clipped off the
    # end, where the cause lives.
    while metrics["total"] > region.width and text_size > 10:
        text_size -= 1
        metrics = _chip_metrics((chip,), scale, text_size)
    bottom = above + _CHIP_GAP * _CHIP_UI_SCALE * scale
    x = (region.width - metrics["total"]) * 0.5
    _draw_chip(
        chip,
        x,
        bottom,
        metrics["widths"][0],
        metrics["height"],
        metrics["padding_x"],
        metrics["padding_y"],
        metrics["text_lift"],
        scale,
    )


def _draw_chip_row(operator, region, scale):
    """Lay the chips out as one centred band, the way yl_bevelflow's HUD does.

    The band belongs to the region rather than the area: the numbers above are region
    pixels too, and a viewport with a toolbar is a few pixels shorter than its area.

    Returns the top edge of the band, which is where the failure notice above it starts
    measuring from.
    """
    chips = _chips(operator)
    if not chips:
        return None
    blf.rotation(_FONT_ID, 0.0)
    text_size = max(10, int(_CHIP_FONT_PIXELS * scale))
    metrics = _chip_metrics(chips, scale, text_size)
    # The wheel has three things it can be pointed at now and each of them names its key,
    # so the row is long enough to meet a narrow viewport.  Shrunk to the same floor the
    # failure notice uses rather than allowed to run off the sides, where a lit chip that
    # is half off-screen reads as a mode that is broken rather than one that is armed.
    while metrics["total"] > region.width and text_size > 10:
        text_size -= 1
        metrics = _chip_metrics(chips, scale, text_size)
    bottom = _CHIP_BOTTOM_MARGIN * scale
    x = (region.width - metrics["total"]) * 0.5
    for chip, width in zip(chips, metrics["widths"]):
        _draw_chip(
            chip,
            x,
            bottom,
            width,
            metrics["height"],
            metrics["padding_x"],
            metrics["padding_y"],
            metrics["text_lift"],
            scale,
        )
        x += width + metrics["item_gap"]
    return bottom + metrics["height"]


def _draw_path_numbers(operator, area, region, scale):
    """Paint one segment count per locked path, centred on it and lifted off its vertices."""
    points = operator.label_points
    values = segment_counts(operator.label_values, operator.label_closed)
    obj = operator.label_object
    if not points or len(values) != len(points) or obj is None:
        return
    blf.size(_FONT_ID, max(12, int(_FONT_PIXELS * scale)))
    blf.enable(_FONT_ID, blf.SHADOW)
    blf.shadow(_FONT_ID, _SHADOW_LEVEL, *_SHADOW_COLOR)
    blf.color(_FONT_ID, *_NUMBER_COLOR)
    view_projection = area.spaces.active.region_3d.perspective_matrix
    matrix_world = obj.matrix_world
    for point, value in zip(points, values):
        text = str(value)
        width, height = blf.dimensions(_FONT_ID, text)
        pixel = _to_pixels(region, view_projection, matrix_world @ point)
        if pixel is None:
            continue
        blf.position(_FONT_ID, pixel[0] - width * 0.5, pixel[1] + height * 0.6, 0.0)
        blf.draw(_FONT_ID, text)
    blf.disable(_FONT_ID, blf.SHADOW)
    blf.color(_FONT_ID, 1.0, 1.0, 1.0, 1.0)


def draw_hud(operator, context):
    """Draw the whole overlay for one scroll session, or nothing if this view is not ours.

    Registered as a ``POST_PIXEL`` handler on the viewport region, which is why the pixel
    coordinates below need no projection of their own.
    """
    area = context.area
    if area is None:
        return
    if not getattr(operator, "labels_shown", False):
        return
    if area.as_pointer() != getattr(operator, "hud_area_ptr", None):
        return
    region = _window_region(area)
    if region is None:
        return
    scale = max(0.1, context.preferences.system.ui_scale)
    row_top = _draw_chip_row(operator, region, scale)
    if row_top is not None:
        _draw_failure_chip(operator, region, scale, row_top)
    _draw_path_numbers(operator, area, region, scale)


def _highlight_geometry(obj):
    """The selected edges of the live edit mesh, as world-space points and segments.

    A step ends by selecting exactly the path edges it just rebuilt, so the live selection
    *is* the answer: reading it back keeps the outline on the mesh as it stands after each
    scroll instead of on the frozen source it came from.  A mesh that is no longer in edit
    mode has no live selection to read and reports nothing.

    Both halves come out of one walk, and the points are de-duplicated: an interior point
    sits on two edges of its own path, and dotting it twice would only waste vertices.
    """
    mesh = getattr(obj, "data", None)
    if mesh is None or not getattr(mesh, "is_editmode", False):
        return (), ()
    try:
        bm = bmesh.from_edit_mesh(mesh)
        matrix_world = obj.matrix_world.copy()
        points = []
        segments = []
        seen = set()
        for edge in bm.edges:
            if not (edge.select and not edge.hide):
                continue
            verts = edge.verts
            segments.append(
                (matrix_world @ verts[0].co, matrix_world @ verts[1].co)
            )
            for vert in verts:
                key = tuple(round(axis, 6) for axis in vert.co)
                if key in seen:
                    continue
                seen.add(key)
                points.append(matrix_world @ vert.co)
        return points, segments
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        # The object went away mid-session; the caller simply draws nothing this frame.
        return (), ()


def _highlight_key(obj, operator):
    """Cheap signature of everything the highlighted edges depend on.

    The batches only have to be rebuilt when the geometry does, and for a while the count
    that produced it was the only thing that could have changed one scroll to the next.
    The shape axes can change it without touching the count, so the outline has to know
    about them too: a stale batch here leaves the highlight tracing the curve the points
    came off rather than the one they are now sitting on.  Reading this costs a copy of the
    matrix and nothing else, so a still viewport rebuilds nothing.
    """
    return (
        getattr(obj.data, "as_pointer", lambda: 0)(),
        tuple(round(value, 6) for row in obj.matrix_world for value in row),
        tuple(getattr(operator, "label_values", ())),
        round(getattr(operator, "label_smooth", 0.0), 6),
        round(getattr(operator, "label_even", 0.0), 6),
    )


def _eye_position(area):
    """Where the camera of this viewport is, in world space.

    Orthographic views keep an eye position in their view matrix, so the same two lines
    serve both projections.  ``None`` says nothing about the view is known, and the caller
    then draws the overlay exactly where it lies without nudging it.
    """
    space = getattr(area, "spaces", None)
    region_3d = getattr(space,"active", None) if space is not None else None
    region_3d = getattr(region_3d, "region_3d", None)
    if region_3d is None:
        return None
    try:
        return region_3d.view_matrix.inverted().translation.copy()
    except (AttributeError, RuntimeError, ValueError):
        return None


def _eye_signature(area):
    """The eye, rounded: two frames orbit apart always differ, a still frame never does."""
    eye = _eye_position(area)
    if eye is None:
        return None
    return tuple(round(value, 4) for value in eye)


def _lifted(coordinate, eye):
    """Slide one point toward the eye by a fraction of how far away the eye is.

    Scaling the whole ray to the eye by a small number is the whole trick: it needs no
    normal, no square root, and it degenerates to nothing when the eye is on the point.
    """
    return coordinate + (eye - coordinate) * _HIGHLIGHT_LIFT


def _lifted_batches(eye):
    """Build the line and point batches for the eye as it sits right now."""
    segments = _HIGHLIGHT["segments"]
    if eye is not None:
        segments = [
            (_lifted(start, eye), _lifted(end, eye)) for start, end in segments
        ]
    coordinates = []
    for start, end in segments:
        coordinates.extend((start, end))
    points = _HIGHLIGHT["points"]
    if eye is not None:
        points = [_lifted(point, eye) for point in points]
    return (
        batch_for_shader(_polyline_shader(), "LINES", {"pos": coordinates}),
        batch_for_shader(_point_shader(), "POINTS", {"pos": list(points)}),
    )


def _highlight_uses_xray(context):
    space = getattr(context, "space_data", None)
    shading = getattr(space, "shading", None) if space is not None else None
    if shading is None:
        return False
    try:
        return bool(shading.show_xray)
    except (AttributeError, RuntimeError, ValueError):
        return False


def draw_highlight(operator, context):
    """Draw a yellow outline over the paths the session is currently resampling.

    Registered as a ``POST_VIEW`` handler, unlike the chip row: these are world-space
    segments rather than region pixels, so they follow the mesh when the viewport orbits
    and are depth tested against it.  ``LESS_EQUAL`` rather than ``NONE`` because the
    outline sits exactly on the surface and should disappear when the mesh turns away.
    """
    area = context.area
    if area is None or not getattr(operator, "highlight_shown", False):
        return
    if area.as_pointer() != getattr(operator, "hud_area_ptr", None):
        return
    obj = getattr(operator, "label_object", None)
    if obj is None:
        return

    # The walk of the mesh is the expensive half, so it is cached on its own and runs only
    # when the geometry behind it could have changed: the mesh itself, its placement, or
    # the count that produced it.
    key = _highlight_key(obj, operator)
    if _HIGHLIGHT["batches"] is None or _HIGHLIGHT["geometry_key"] != key:
        _HIGHLIGHT["points"], _HIGHLIGHT["segments"] = _highlight_geometry(obj)
        _HIGHLIGHT["geometry_key"] = key
        _HIGHLIGHT["batches"] = None
    if not _HIGHLIGHT["points"] or not _HIGHLIGHT["segments"]:
        return

    # The nudge is the cheap half and runs whenever the eye moves: the pixels the dots cover
    # do not change, but the surface around them that they have to beat does.
    view = _eye_signature(area)
    if _HIGHLIGHT["batches"] is None or _HIGHLIGHT["view"] != view:
        _HIGHLIGHT["batches"] = _lifted_batches(_eye_position(area))
        _HIGHLIGHT["view"] = view
    lines_batch, points_batch = _HIGHLIGHT["batches"]

    scale = max(0.1, context.preferences.system.ui_scale)
    viewport = gpu.state.viewport_get()
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE" if _highlight_uses_xray(context) else "LESS_EQUAL")

    # The polyline shader has to be told how wide a line is in device pixels, and the
    # point shader how big a dot is: neither state carries over from the other.
    shader = _polyline_shader()
    shader.bind()
    shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
    shader.uniform_float("lineWidth", _HIGHLIGHT_WIDTH)
    shader.uniform_float("color", _HIGHLIGHT_COLOR)
    lines_batch.draw(shader)

    # gl_PointSize only reaches the driver with program point size switched on, and the
    # size tracks the interface scale so a dot stays a dot on a hi-dpi display.
    dot_shader = _point_shader()
    dot_size = _HIGHLIGHT_POINT_SIZE * scale
    gpu.state.program_point_size_set(True)
    gpu.state.point_size_set(dot_size)
    dot_shader.bind()
    dot_shader.uniform_float("color", _HIGHLIGHT_POINT_COLOR)
    dot_shader.uniform_float("size", dot_size)
    points_batch.draw(dot_shader)
    gpu.state.point_size_set(1.0)
    gpu.state.program_point_size_set(False)

    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("NONE")


def clear_box_cache():
    """Forget every rounded chip box so the next frame rebuilds its geometry."""
    _BOX_CACHE.clear()


def clear_highlight_cache():
    """Forget the readings of the mesh and the batches drawn from them."""
    _HIGHLIGHT.update(
        points=(), segments=(), batches=None, geometry_key=None, view=None
    )

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

That lesson is why the second half of this file exists.  A refusal can also happen before a
session starts -- the selection on screen is not one the tool can use -- and then there is no
modal, no chip row and no operator left to report through, so the only thing the user gets is
a header message that a single click wipes out.  So the notice lives here rather than on the
operator: a warning chip of its own, the offending vertices and edges marked red on the mesh
under it, and a timer that takes it away again.
"""

import blf
import bpy
import gpu
import math

import bmesh
from collections import OrderedDict
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from ..i18n import pgettext
from ..operators import FAILURE_PREFIX
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
_HIGHLIGHT = {
    "points": (),
    "segments": (),
    "batches": None,
    "geometry_key": None,
}

# A refusal that came before any session existed.  Unlike the highlight, this one holds
# coordinates rather than reading them off the mesh: the mesh was never touched, and what
# has to be marked is the selection the tool refused.
_NOTICE_COLOR = (1.0, 0.2, 0.2, 1.0)
_NOTICE_WIDTH = 3.0
_NOTICE_POINT_SIZE = 10.0
_NOTICE_SECONDS = 8.0
_NOTICE = {
    "text": "",
    "points": (),
    "segments": (),
    "area": None,
    "pixel_handler": None,
    "view_handler": None,
    "batches": None,
}

_CHIP_FONT_PIXELS = 18
_CHIP_BOTTOM_MARGIN = 80.0
# The failure notice is the planner's own sentence, with the operator-wide "failed safely"
# wrapper taken off: the overlay is the only screen the user is looking at, and the
# wrapper just repeats that there is a notice.  A reason longer than a viewport is wide
# gets its tail cut, because the cause is always in the front half of the sentence.
_FAILURE_LIMIT = 96
# A refusal that came before the session got as far as starting has nowhere to be squeezed,
# so it is allowed the whole sentence and a smaller font instead of a cut ending.
_NOTICE_LIMIT = 220
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


def _failure_text(message, limit=_FAILURE_LIMIT):
    """A planner failure as the sentence that fits in a chip.

    The wrapper is looked up rather than hard-coded because the operator already put the
    translated one on: in another locale the message arrives in Chinese and stripping an
    English prefix off it would leave the notice describing a failure twice over.

    ``limit`` is looser for a standalone notice than for a chip squeezed in above the row:
    the sentences that explain a refused selection put the cure at the end, where a chip
    would cut it off.
    """
    if message is None:
        return ""
    text = str(message)
    prefix = pgettext(FAILURE_PREFIX)
    if text.startswith(prefix):
        text = text[len(prefix) :]
    text = " ".join(text.split())
    if limit is not None and len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
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


def _counts_text(values, closed):
    """Segment counts as one number when they all agree, as a list when they do not.

    Many paths at the same count are one state, not a row of identical numbers: five edges
    at five segments each read as "5, 5, 5, 5, 5" and say less than "5" does.
    """
    counts = segment_counts(values, closed)
    distinct = set(counts)
    if len(distinct) == 1:
        return str(next(iter(distinct)))
    return ", ".join(str(count) for count in counts)


def _chips(operator):
    """The three axes and the two clicks, as the typed parts yl_bevelflow's chip row takes.

    Every axis names the key that claims the wheel, armed or not, so the row reads as a
    list of what drives what and the lit one is where the next tick lands.  Under a held
    modifier that lit chip is also the only confirmation on screen that the key was heard at
    all: the wheel is doing something other than what it does by default, and nothing on the
    mesh says why.

    Only the armed axis is lit.  The count chip used to go red when the wheel was pointed
    elsewhere, which read as a warning about a count that is doing exactly what it should.

    The count reads entry → current, because a scroll carries every locked path by the same
    amount rather than driving them to one shared number: where the wheel started is the only
    reference that makes a tick readable.  Both halves collapse to one number when the paths
    agree, so five edges at five segments each read "5 → 6" rather than two rows of fives.

    The strengths are the ones that reached a mesh rather than the ones the wheel was last
    turned to, which is the same rule the count already follows: a refused step leaves the
    previous mesh standing, and a chip that moved anyway would be describing a mesh that is
    not there.
    """
    mode = getattr(operator, "mode", MODE_COUNT)
    closed = operator.label_closed
    return (
        {
            "text": pgettext("[Wheel] Segments {entry} → {current}").format(
                entry=_counts_text(operator.entry_counts, closed),
                current=_counts_text(operator.label_values, closed),
            ),
            "type": "hotkey_active" if mode == MODE_COUNT else "hotkey",
        },
        {
            "text": pgettext("[Shift] Smooth")
            + _strength_text(operator, "label_smooth"),
            "type": "hotkey_active" if mode == MODE_SMOOTH else "hotkey",
        },
        {
            "text": pgettext("[Ctrl] Even")
            + _strength_text(operator, "label_even"),
            "type": "hotkey_active" if mode == MODE_EVEN else "hotkey",
        },
        # One button, mouse only: this is a scroll interaction, and the keyboard version
        # of keep and revert would need keys Blender has already handed to other tools.
        {"text": pgettext("[LMB] Keep   [RMB] Revert"), "type": "hotkey"},
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


def _draw_chip(chip, x, bottom, width, box_height, padding_x, padding_y, text_lift):
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
        _CHIP_RADIUS,
        1.0,
    )
    blf.color(_FONT_ID, *text_color)
    blf.position(_FONT_ID, x + padding_x, bottom + padding_y + text_lift, 0.0)
    blf.draw(_FONT_ID, chip["text"])


def _chip_metrics(chips, text_size=None):
    """Widths, height and total run of a row of chips, in region pixels.

    Nothing here is multiplied by the interface scale, because yl_bevelflow's row is not
    either: his measures are his own fixed spacing and that is the size they land at on
    screen.  Multiplying them by ``ui_scale`` on top made this band a size larger than the
    one his HUD draws.

    ``text_size`` is let through because both the row and the failure notice have to fit
    the region they are drawn in, and the only way to know that is to measure at a size and
    try a smaller one: the notice because it is a sentence rather than a label, and the row
    because four labelled chips are a wider thing than two were.
    """
    ui_scale = _CHIP_UI_SCALE
    padding_x = _CHIP_PADDING_X * ui_scale
    padding_y = _CHIP_PADDING_Y * ui_scale
    item_gap = _CHIP_GAP * ui_scale
    if text_size is None:
        text_size = _CHIP_FONT_PIXELS
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


def _draw_warning(region, text, bottom):
    """One warning chip on a row of its own, centred at ``bottom`` pixels from the region's floor.

    A planner sentence is longer than every label in the chip row put together, so it gets
    a line to itself rather than joining it, and the warning red says it is news rather
    than something to press.
    """
    chip = {"text": text, "type": "warning"}
    text_size = _CHIP_FONT_PIXELS
    metrics = _chip_metrics((chip,), text_size)
    # One pixel at a time, and only down to the same floor the row uses: a reason nobody
    # can read is no reason at all, but a reason wider than the window is clipped off the
    # end, where the cause lives.
    while metrics["total"] > region.width and text_size > 10:
        text_size -= 1
        metrics = _chip_metrics((chip,), text_size)
    _draw_chip(
        chip,
        (region.width - metrics["total"]) * 0.5,
        bottom,
        metrics["widths"][0],
        metrics["height"],
        metrics["padding_x"],
        metrics["padding_y"],
        metrics["text_lift"],
    )


def _draw_failure_chip(operator, region, above):
    """The refusal to a scroll, on a row above the chips.

    Silence would be the other option -- the wheel does nothing, after all -- but a wheel
    that does nothing and says nothing is indistinguishable from a wheel the operator is
    not listening to.
    """
    message = _failure_text(getattr(operator, "message", None))
    if not message:
        return
    _draw_warning(region, message, above + _CHIP_GAP * _CHIP_UI_SCALE)


def _draw_chip_row(operator, region):
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
    text_size = _CHIP_FONT_PIXELS
    metrics = _chip_metrics(chips, text_size)
    # The wheel has three things it can be pointed at now and each of them names its key,
    # so the row is long enough to meet a narrow viewport.  Shrunk to the same floor the
    # failure notice uses rather than allowed to run off the sides, where a lit chip that
    # is half off-screen reads as a mode that is broken rather than one that is armed.
    while metrics["total"] > region.width and text_size > 10:
        text_size -= 1
        metrics = _chip_metrics(chips, text_size)
    bottom = _CHIP_BOTTOM_MARGIN
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
    row_top = _draw_chip_row(operator, region)
    if row_top is not None:
        _draw_failure_chip(operator, region, row_top)
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


def _highlight_batches():
    """The line and point batches for the highlighted paths, at the coordinates they have.

    Nothing is nudged toward the eye: a lift along that ray looks pixel-preserving in a
    perspective view and is not one in an orthographic view, where the eye is a point on the
    view axis -- every lifted coordinate then slides toward the middle of the viewport as the
    view orbits, which is the outline drifting off the mesh it marks.  Drawn where they lie
    the batches cannot move independently of the mesh, and they no longer depend on the view
    at all.  What they give up is the depth test on a surface tilted away from the camera.
    """
    coordinates = []
    for start, end in _HIGHLIGHT["segments"]:
        coordinates.extend((start, end))
    return (
        batch_for_shader(_polyline_shader(), "LINES", {"pos": coordinates}),
        batch_for_shader(_point_shader(), "POINTS", {"pos": list(_HIGHLIGHT["points"])}),
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
    # when the geometry behind it could have changed: the mesh itself, its placement, or the
    # count that produced it.  The batches ride along with it now that nothing about them
    # depends on the view.
    key = _highlight_key(obj, operator)
    if _HIGHLIGHT["batches"] is None or _HIGHLIGHT["geometry_key"] != key:
        _HIGHLIGHT["points"], _HIGHLIGHT["segments"] = _highlight_geometry(obj)
        _HIGHLIGHT["geometry_key"] = key
        _HIGHLIGHT["batches"] = None
    if not _HIGHLIGHT["points"] or not _HIGHLIGHT["segments"]:
        return
    if _HIGHLIGHT["batches"] is None:
        _HIGHLIGHT["batches"] = _highlight_batches()
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


def show_notice(context, area, message, points=(), segments=()):
    """Say in the viewport why an action was refused when there is no session to say it.

    A refusal can come before the operator has started: the selection on screen is not one
    this tool can use, so it locks nothing and returns, and then nothing on screen belongs
    to us -- no chip row, no numbers, and a header report that the next click wipes out.
    That is the exact shape of "I pressed it and nothing happened".

    ``points`` and ``segments`` are world-space coordinates for the elements to blame, and
    either can be empty, because a refusal with nothing selected has no *where* to show --
    only a *what to select instead*.

    ``area`` is the viewport to draw in rather than the caller's own, because a call deferred
    out of a menu has no area of its own to hand over -- see ``_viewport_area``.
    """
    hide_notice()
    text = _failure_text(message, limit=_NOTICE_LIMIT)
    if area is None or not text:
        return
    _NOTICE["text"] = text
    _NOTICE["points"] = tuple(Vector(point) for point in points)
    _NOTICE["segments"] = tuple(
        (Vector(start), Vector(end)) for start, end in segments
    )
    _NOTICE["area"] = area
    _NOTICE["pixel_handler"] = bpy.types.SpaceView3D.draw_handler_add(
        _draw_notice, (area,), "WINDOW", "POST_PIXEL"
    )
    if _NOTICE["points"] or _NOTICE["segments"]:
        _NOTICE["view_handler"] = bpy.types.SpaceView3D.draw_handler_add(
            _draw_notice_geometry, (area, context), "WINDOW", "POST_VIEW"
        )
    bpy.app.timers.register(_notice_expired, first_interval=_NOTICE_SECONDS)
    area.tag_redraw()


def hide_notice():
    """Take a refusal off the viewport, if one is still standing."""
    _clear_notice()
    if bpy.app.timers.is_registered(_notice_expired):
        bpy.app.timers.unregister(_notice_expired)


def _notice_expired():
    """One-shot: the notice has had its say.

    It does not unregister itself -- returning ``None`` is how a timer retires, and calling
    ``unregister`` on a timer from inside its own callback is not something to rely on.
    """
    _clear_notice()
    return None


def _clear_notice():
    if _NOTICE["pixel_handler"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_NOTICE["pixel_handler"], "WINDOW")
        _NOTICE["pixel_handler"] = None
    if _NOTICE["view_handler"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_NOTICE["view_handler"], "WINDOW")
        _NOTICE["view_handler"] = None
    area = _NOTICE["area"]
    _NOTICE.update(text="", points=(), segments=(), batches=None, area=None)
    if area is not None:
        try:
            area.tag_redraw()
        except ReferenceError:
            pass


def _draw_notice(area):
    """The refusal sentence, on the row the chip band would have used.

    Same height as the scroll's own chips because this is the step the scroll never got to
    start; with nothing else drawn there is nothing for it to overlap.
    """
    if not _NOTICE["text"]:
        return
    try:
        region = _window_region(area)
    except (AttributeError, ReferenceError, RuntimeError):
        return
    if region is None:
        return
    _draw_warning(region, _NOTICE["text"], _CHIP_BOTTOM_MARGIN)


def _draw_notice_geometry(area, context):
    """Red dots and segments over the elements the refusal named.

    Drawn through the mesh instead of depth tested against it: the vertex to blame is
    usually the one buried in the shape, and a mark that hides behind a face has not told
    anyone where to look.  Like the session highlight, these coordinates are left exactly
    where they are -- no lift toward the eye, which drifts in an orthographic view.
    """
    points = _NOTICE["points"]
    segments = _NOTICE["segments"]
    if not points and not segments:
        return
    if _NOTICE["batches"] is None:
        coordinates = []
        for start, end in segments:
            coordinates.extend((start, end))
        _NOTICE["batches"] = (
            batch_for_shader(_polyline_shader(), "LINES", {"pos": coordinates})
            if coordinates
            else None,
            batch_for_shader(_point_shader(), "POINTS", {"pos": list(points)})
            if points
            else None,
        )
    lines, dots = _NOTICE["batches"]

    viewport = gpu.state.viewport_get()
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")

    if lines is not None:
        shader = _polyline_shader()
        shader.bind()
        shader.uniform_float("viewportSize", (viewport[2], viewport[3]))
        shader.uniform_float("lineWidth", _NOTICE_WIDTH)
        shader.uniform_float("color", _NOTICE_COLOR)
        lines.draw(shader)
    if dots is not None:
        scale = max(0.1, context.preferences.system.ui_scale)
        size = _NOTICE_POINT_SIZE * scale
        shader = _point_shader()
        gpu.state.program_point_size_set(True)
        gpu.state.point_size_set(size)
        shader.bind()
        shader.uniform_float("color", _NOTICE_COLOR)
        shader.uniform_float("size", size)
        dots.draw(shader)
        gpu.state.point_size_set(1.0)
        gpu.state.program_point_size_set(False)

    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("NONE")


def clear_box_cache():
    """Forget every rounded chip box so the next frame rebuilds its geometry."""
    _BOX_CACHE.clear()


def clear_highlight_cache():
    """Forget the readings of the mesh and the batches drawn from them."""
    _HIGHLIGHT.update(points=(), segments=(), batches=None, geometry_key=None)

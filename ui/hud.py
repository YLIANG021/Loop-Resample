"""The resample heads-up display: the counts on the paths, and the keys along the bottom.

Two things anchor the numbers and they pull in opposite directions.  A count sits where the
user's selection is, a point in the 3D view, so the view matrices are walked by hand: Blender
exposes no world-to-pixel helper for a viewport that is not a camera.  Which point it sits on
comes from the curve the step was built on, not the rebuilt mesh, whose vertex count changes every
scroll and would make the label hop with it.  A path's halfway point survives a rebuild, so the
operator hands one over per step.

The number is segments, not points.  See ``segment_counts`` for why that is one less than the
planner's count.

The chip row is a readout, not a control: nothing in it is clickable.  It names the axis the wheel
is pointed at, how far along it the standing mesh sits, and any refusal, as a warning chip.

A refusal can also come before a session starts, when the selection on screen is not one the tool
can use: no modal, no chip row, no operator to report through, and a header message the next click
wipes out.  That notice lives here instead, as its own warning chip plus a timer; see
``show_notice``.
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
# The counts sit on the mesh: bright yellow on a dark halo, because yellow alone washes out
# against pale shading or a pale material and a bright-on-bright shadow would hide them.
_NUMBER_COLOR = (1.0, 0.95, 0.1, 1.0)
_SHADOW_COLOR = (0.05, 0.05, 0.05, 0.85)

# The adjusted paths, traced over the mesh they are rebuilt on.  Two colours, two things said:
# the edge is what got resampled, so it is fluorescent green and reads as a line; the point on it
# carries the number above it, so the dot is that same yellow.
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

# A refusal from before any session existed: a sentence and nothing marked on the mesh, which the
# tool never touched.
_NOTICE_SECONDS = 1.5
_NOTICE = {
    "text": "",
    "area": None,
    "pixel_handler": None,
}

_CHIP_FONT_PIXELS = 18
_CHIP_BOTTOM_MARGIN = 80.0
# The failure notice is the planner's own sentence with the operator-wide "failed safely" wrapper
# off: the overlay is the only screen the user is looking at, so the wrapper only repeats that
# there is a notice.  A reason wider than the viewport loses its tail; the cause is always in the
# front half of the sentence.
_FAILURE_LIMIT = 96
# A refusal from before the session started has nowhere to be squeezed, so it gets the whole
# sentence and a smaller font instead of a cut ending.
_NOTICE_LIMIT = 220
# The chip row's spacing is a fixed 1.3 * 0.96 scale and the text is lifted off its padding by
# hand, so the band is measured in its own pixels rather than in interface units.
_CHIP_BUTTON_SCALE = 0.96
_CHIP_UI_SCALE = 1.3 * _CHIP_BUTTON_SCALE
_CHIP_PADDING_X = 9.0
_CHIP_PADDING_Y = 5.0
# Written as the pixel measure it has to produce, because that is what the armed chip is
# measured against: a plate has to stay clear of its neighbour's first glyph, one gap plus one
# of that neighbour's own paddings away.  A raw 4.0 under the 1.248 scale left no room for a
# chip grown to 115%; twelve bought the clearance, fifteen is looser than needed.  Ten is tight:
# the armed plate of the longest counts reading grows 19 pixels past its own edge, and ten of
# gap plus a neighbour's 11 of padding is 21.2, two pixels to spare that a longer reading would
# spend.
_CHIP_GAP = 10.0 / _CHIP_UI_SCALE
_CHIP_TEXT_LIFT = 3.0
_CHIP_RADIUS = 8.0
# The ring every plate is drawn with.  One pixel read as no ring: the outline is a grey two steps
# above the fill, and a one pixel band is thinner than the seam between the plate and what it is
# laid over, so the row looked like borderless boxes rather than boxes with a quiet edge.
_CHIP_BORDER = 2.0
# The armed chip is also the bigger one.  Size says what the lit colour already said, which axis
# the wheel is pointed at, but says it the instant the key goes down rather than as a shade the
# eye has to compare against a neighbour.  Plate and glyphs grow together about the chip's own
# centre, so the padding keeps its proportion whatever the multiplier.  A multiplier buys overlap
# in proportion to the chip's width, so 7.5% reaches further on a long reading than a short label:
# that is why it is this modest, since it has to suit the widest thing the row shows, a dozen
# characters spending 19 of the 21.2 pixels the gap leaves.  It reaches the glyphs only in whole
# points: 1.028 to 1.083 draws at 19 pixels, 1.084 to 1.138 at 20, 1.139 to 1.194 at 21, so
# between those it is the plate being sized and crossing one moves the text a whole pixel.
_CHIP_ARM_SCALE = 1.075
_CHIP_STYLES = {
    "warning": (
        (0.40, 0.12, 0.12, 0.88),
        (0.68, 0.22, 0.22, 0.95),
        (1.0, 0.82, 0.82, 1.0),
    ),
    # The armed chip wears the entry mark's own yellow (#FFE400, icons/loop_resample.png), so
    # fill and ring are hue-shifted with the glyphs rather than left on blue.
    "hotkey_active": (
        (0.42, 0.37, 0.08, 0.50),
        (0.68, 0.60, 0.12, 0.95),
        (1.0, 0.894, 0.0, 1.0),
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
    """The point half the path's own length along from its first vertex, in local coordinates.

    Off the frozen source, so a position in the mesh rather than on the screen.  For a closed
    loop "halfway" is measured from whichever vertex the sampler started on, which never moves.
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

    An open path of ``n`` points has ``n - 1`` edges; a closed loop of ``n`` has ``n``, its last
    one closing back onto the first.  Recomputed per label rather than stored, so the stored
    numbers stay the planner's and a count is translated once, when it is drawn or reported.
    """
    return tuple(
        points if closed else points - 1
        for points, closed in zip(point_counts, closed_flags)
    )


def _failure_text(message, limit=_FAILURE_LIMIT):
    """A planner failure as the sentence that fits in a chip.

    The wrapper is looked up rather than hard-coded because the operator already put the
    translated one on: in another locale, stripping an English prefix off a Chinese message
    would leave the notice describing a failure twice over.  ``limit`` is looser for a standalone
    notice, because those sentences put the cure at the end, where a chip would cut it off.
    """
    if message is None:
        return ""
    text = str(message)
    prefix = pgettext(FAILURE_PREFIX)
    text = text.removeprefix(prefix)
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

    ``perspective_matrix`` already folds the view and window transforms together.  The point goes
    in as a homogeneous 4-vector: a 3-vector comes back three-wide with ``w`` dropped, leaving
    nothing to divide by.
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
    """The round, soft-edged dot the path points are drawn with.

    The built-in point shader squares off at the edges and takes no antialiasing, and a row of
    those reads as a dashed ruler.
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


def _rounded_box_batches(width, height, radius, border_width, shader, resolution=12):
    """The two triangle batches of a rounded rectangle, fill and outline, ready to draw.

    The key quantises the size so a chip that changes width by a pixel when the count gains a
    digit keeps its batch.  Vertices are offset from the box's own bottom-left rather than the
    region's, so one batch serves a chip that moves: its position is a matrix translation at draw
    time.
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
        batch_for_shader(
            shader,
            "TRIS",
            {"pos": [(width / 2.0, height / 2.0)] + list(inner_verts)},
            indices=background_indices,
        ),
        batch_for_shader(
            shader,
            "TRIS",
            {"pos": list(outer_verts) + list(inner_verts)},
            indices=border_indices,
        ),
    )
    _BOX_CACHE[key] = cached
    while len(_BOX_CACHE) > _BOX_CACHE_LIMIT:
        _BOX_CACHE.popitem(last=False)
    return cached


def _draw_rounded_box(x, y, width, height, background, border, radius, border_width):
    """A filled rounded rectangle with an outline, in region pixels from the bottom left."""
    radius = min(radius, min(width, height) / 2)
    shader = _uniform_color_shader()
    background_batch, border_batch = _rounded_box_batches(
        width, height, radius, border_width, shader
    )
    shader.bind()
    gpu.state.blend_set("ALPHA")
    gpu.matrix.push()
    gpu.matrix.translate((x, y, 0.0))
    shader.uniform_float("color", background)
    background_batch.draw(shader)
    shader.uniform_float("color", border)
    border_batch.draw(shader)
    gpu.matrix.pop()
    gpu.state.blend_set("NONE")


def _counts_text(values, closed):
    """Segment counts as one number when they all agree, as a list when they do not.

    Five edges at five segments each say more as "5" than as "5, 5, 5, 5, 5".
    """
    counts = segment_counts(values, closed)
    distinct = set(counts)
    if len(distinct) == 1:
        return str(next(iter(distinct)))
    return ", ".join(str(count) for count in counts)


def _chips(operator):
    """The three axes and the two clicks, as the typed parts the chip row takes.

    Every axis names the key that claims the wheel, armed or not, so the row reads as what drives
    what and the lit one is where the next tick lands.  Under a held modifier that lit chip is the
    only confirmation on screen that the key was heard: the wheel is doing something other than
    its default and nothing on the mesh says why.  The count chip used to go red when the wheel
    pointed elsewhere, which read as a warning about a count doing exactly what it should.

    The count reads entry → current because a scroll carries every locked path by the same amount
    rather than to one shared number, so where the wheel started is the only reference that makes
    a tick readable.  The strengths are likewise the ones that reached a mesh, not the ones the
    wheel was last turned to: a refused step leaves the previous mesh standing.
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

    Zero is the source curve, the one position on these axes with no strength to read, so it
    leaves the chip bare.  Past it the chip reads a percentage, what a scroll actually chose: an
    axis with one function is only ever raised further.
    """
    value = getattr(operator, attribute, 0.0)
    if value == 0.0:
        return ""
    return " " + str(int(round(value * 100))) + "%"


def _draw_chip(
    chip,
    x,
    bottom,
    width,
    box_height,
    padding_x,
    padding_y,
    text_lift,
    text_size,
    scale=1.0,
):
    """One chip: a rounded box, text lifted off its padding, an outline two pixels wide.

    ``width``, ``box_height`` and the two offsets are the chip's resting measures, the ones the
    row was laid out with; ``scale`` grows the drawing about the chip's own centre.  A grown chip
    cannot push its neighbours, because only the plate and glyphs move.
    """
    background, outline, text_color = _CHIP_STYLES.get(
        chip.get("type"), _CHIP_STYLES["label"]
    )
    center_x = x + width * 0.5
    center_y = bottom + box_height * 0.5
    grown_width = width * scale
    grown_height = box_height * scale
    _draw_rounded_box(
        center_x - grown_width * 0.5,
        center_y - grown_height * 0.5,
        grown_width,
        grown_height,
        background,
        outline,
        _CHIP_RADIUS * scale,
        _CHIP_BORDER,
    )
    blf.size(_FONT_ID, max(1, int(round(text_size * scale))))
    blf.color(_FONT_ID, *text_color)
    blf.position(
        _FONT_ID,
        center_x + (x + padding_x - center_x) * scale,
        center_y + (bottom + padding_y + text_lift - center_y) * scale,
        0.0,
    )
    blf.draw(_FONT_ID, chip["text"])


def _chip_metrics(chips, text_size=None):
    """Widths, height and total run of a row of chips, in region pixels.

    Nothing here is multiplied by the interface scale: the paddings and the gap are already the
    pixels they should land at, and scaling them on top grew the band past the spacing they
    describe.  ``text_size`` is let through because the row and the failure notice both have to
    fit their region, and the only way to know is to measure at a size and try a smaller one.
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
    """One warning chip on a row of its own, centred at ``bottom`` pixels off the floor.

    A planner sentence is longer than every label in the chip row put together, so it gets a line
    to itself rather than joining it.
    """
    chip = {"text": text, "type": "warning"}
    text_size = _CHIP_FONT_PIXELS
    metrics = _chip_metrics((chip,), text_size)
    # Shrunk a pixel at a time, and only to the row's own floor: a reason wider than the window is
    # clipped off the end, where the cause lives.
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
        text_size,
    )


def _draw_failure_chip(operator, region, above):
    """The refusal to a scroll, on a row above the chips.

    Silence would read as an operator that is not listening.
    """
    message = _failure_text(getattr(operator, "message", None))
    if not message:
        return
    _draw_warning(region, message, above + _CHIP_GAP * _CHIP_UI_SCALE)


def _draw_chip_row(operator, region):
    """Lay the chips out as one band, centred horizontally near the bottom of the region.

    The band belongs to the region, not the area: the numbers are region pixels too, and a
    viewport with a toolbar is a few pixels shorter than its area.  Returns the top edge of the
    band, where the failure notice above it starts measuring from.
    """
    chips = _chips(operator)
    if not chips:
        return None
    blf.rotation(_FONT_ID, 0.0)
    text_size = _CHIP_FONT_PIXELS
    metrics = _chip_metrics(chips, text_size)
    # Three things the wheel can be pointed at, each naming its key, so the row can meet a narrow
    # viewport.  Shrunk to the failure notice's floor rather than allowed off the sides, where a
    # half-visible lit chip reads as a broken mode rather than an armed one.
    while metrics["total"] > region.width and text_size > 10:
        text_size -= 1
        metrics = _chip_metrics(chips, text_size)
    bottom = _CHIP_BOTTOM_MARGIN
    x = (region.width - metrics["total"]) * 0.5
    laid_out = []
    for chip, width in zip(chips, metrics["widths"]):
        laid_out.append((chip, x, width))
        x += width + metrics["item_gap"]
    # Resting measures through the whole layout, so the armed chip is the only thing that moves:
    # a row that shuffled sideways on every keypress would read as the band flickering.  It does
    # overhang its neighbours, and going last makes that a plate laid on the row instead of a
    # neighbour with a bite taken out.
    for armed in (False, True):
        for chip, chip_x, width in laid_out:
            if (chip["type"] == "hotkey_active") is not armed:
                continue
            _draw_chip(
                chip,
                chip_x,
                bottom,
                width,
                metrics["height"],
                metrics["padding_x"],
                metrics["padding_y"],
                metrics["text_lift"],
                text_size,
                (_CHIP_ARM_SCALE if armed else 1.0),
            )
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

    A ``POST_PIXEL`` handler on the viewport region, which is why the pixel coordinates below need
    no projection of their own.
    """
    # The context is the one captured when the modal started, so reading it is the only part that
    # can meet a dead area.  A raise out of a draw handler costs the whole viewport its overlays,
    # and Blender does not say which handler threw.
    try:
        area = context.area
        scale = max(0.1, context.preferences.system.ui_scale)
    except (AttributeError, ReferenceError, RuntimeError):
        return
    if area is None:
        return
    if not getattr(operator, "labels_shown", False):
        return
    if area.as_pointer() != getattr(operator, "hud_area_ptr", None):
        return
    region = _window_region(area)
    if region is None:
        return
    row_top = _draw_chip_row(operator, region)
    if row_top is not None:
        _draw_failure_chip(operator, region, row_top)
    _draw_path_numbers(operator, area, region, scale)


def _highlight_geometry(obj):
    """The selected edges of the live edit mesh, as world-space points and segments.

    A step ends by selecting exactly the path edges it has rebuilt, so the live selection is the
    answer, and reading it back keeps the outline on the mesh as it stands after each scroll
    instead of on the frozen source.  The points are de-duplicated: an interior point sits on two
    edges of its path, and dotting it twice only wastes vertices.
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
        # The object went away mid-session; the caller draws nothing this frame.
        return (), ()


def _highlight_key(obj, operator):
    """Cheap signature of everything the highlighted edges depend on.

    The batches only need rebuilding when the geometry does.  The shape axes can change it without
    touching the count, so they belong in the key too: a stale batch leaves the highlight tracing
    the curve the points came off rather than the one they sit on now.  Reading this costs a copy
    of the matrix, so a still viewport rebuilds nothing.
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

    Nothing is nudged toward the eye.  A lift along that ray looks pixel-preserving in a
    perspective view and is not in an orthographic one, where the eye is a point on the view axis:
    every lifted coordinate slides toward the middle of the viewport as the view orbits, and the
    outline drifts off the mesh it marks.  Drawn where they lie the batches no longer depend on
    the view at all, and cannot move independently of the mesh.  They give up the depth test on a
    surface tilted away from the camera.
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

    A ``POST_VIEW`` handler, unlike the chip row: these are world-space segments rather than
    region pixels, so they follow the mesh when the viewport orbits and are depth tested against
    it.  ``LESS_EQUAL`` rather than ``NONE`` because the outline sits exactly on the surface and
    should disappear when the mesh turns away.
    """
    # Same stale-context read as draw_hud: both handlers were handed the invoke-time context.
    try:
        area = context.area
    except (AttributeError, ReferenceError, RuntimeError):
        return
    if area is None or not getattr(operator, "highlight_shown", False):
        return
    if area.as_pointer() != getattr(operator, "hud_area_ptr", None):
        return
    obj = getattr(operator, "label_object", None)
    if obj is None:
        return

    # The mesh walk is the expensive half, so it is cached on its own and reruns only when the
    # geometry behind it could have changed.  The batches ride along now that nothing about them
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


def show_notice(area, message):
    """Say in the viewport why an action was refused when there is no session to say it.

    A refusal can come before the operator has started, when the selection is not one this tool
    can use: it locks nothing and returns, nothing on screen belongs to us, and the header report
    is wiped by the next click.

    The sentence is the whole of it.  Where the trouble sits used to be dotted onto the mesh in
    red, and that was taken out: it needed a handler that survives a viewport swap, it drew
    through the geometry, and what it pointed at was one vertex in a hundred the user cannot pick
    out anyway.

    ``area`` is the viewport to draw in rather than the caller's own, because a call deferred out
    of a menu has no area to hand over (see ``_viewport_area``).
    """
    hide_notice()
    text = _failure_text(message, limit=_NOTICE_LIMIT)
    if area is None or not text:
        return
    _NOTICE["text"] = text
    _NOTICE["area"] = area
    _NOTICE["pixel_handler"] = bpy.types.SpaceView3D.draw_handler_add(
        _draw_notice, (area,), "WINDOW", "POST_PIXEL"
    )
    bpy.app.timers.register(_notice_expired, first_interval=_NOTICE_SECONDS)
    area.tag_redraw()


def hide_notice():
    """Take a refusal off the viewport, if one is still standing."""
    _clear_notice()
    if bpy.app.timers.is_registered(_notice_expired):
        bpy.app.timers.unregister(_notice_expired)


def _notice_expired():
    """One-shot timer callback.

    Returning ``None`` is how a timer retires.  It does not unregister itself, because calling
    ``unregister`` from inside a timer's own callback is not something to rely on.
    """
    _clear_notice()
    return None


def _clear_notice():
    if _NOTICE["pixel_handler"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_NOTICE["pixel_handler"], "WINDOW")
        _NOTICE["pixel_handler"] = None
    area = _NOTICE["area"]
    _NOTICE.update(text="", area=None)
    if area is not None:
        try:
            area.tag_redraw()
        except ReferenceError:
            pass


def _draw_notice(area):
    """The refusal sentence, on the row the chip band would have used.

    Same height as the scroll's own chips, because this is a scroll that never got to start; with
    nothing else drawn there is nothing to overlap.
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


def clear_box_cache():
    """Forget every rounded chip box so the next frame rebuilds its batches."""
    _BOX_CACHE.clear()


def clear_highlight_cache():
    """Forget the readings of the mesh and the batches drawn from them."""
    _HIGHLIGHT.update(points=(), segments=(), batches=None, geometry_key=None)

"""Scroll-to-set interaction for a resample session it starts itself.

The skeleton is yl_bevelflow's: a ``POST_PIXEL`` draw handler tied to the operator's own
life, the wheel for single steps, and one hook per outcome.  Three things are deliberately
not copied.  The number is painted on the path it belongs to instead of into a box at the
middle of the screen; the chips below it are worded for this operator; and nothing here
reads the mouse position, because a sideways drag turns a view navigation into a hundred
new points.  The wheel is the control, the overlay is the readout, and the keyboard is not
part of the deal: no key confirms, no key cancels, because the two outcomes each have a
click of their own and the rest of Blender's keys belong to other tools.

The one thing the keyboard does now is say which effect the next tick belongs to, and only
while a modifier is held down for it -- see
:meth:`MESH_OT_loop_resample_interactive._track_modifiers`.  That is a mode selector rather
than an input channel: the wheel stays the only thing that moves anything, the keys carry no
value of their own, and letting go hands the wheel back to the counts it defaults to.  Shift
arms one effect -- smoothing the locked curves -- and Ctrl another -- evening their points
out; both are one-way, so a tick strengthens the armed effect whichever way the wheel turns,
and only the right-click that reverts the session puts it back.

The right-click menu runs this operator through a forwarder, which makes the operator
responsible for both ends of the life: it locks the mesh on the way in -- that used to be a
separate click -- and it drops the session on the way out, because a session that outlives
the scroll that owns it would leave the next click adjusting the mesh from the previous
selection.  Every step the planner refuses is written onto the overlay, because this
overlay is now the only interface there is: a scroll that silently does nothing reads as
a broken wheel.

Scrolling rebuilds the mesh for real, once per step rather than once per event: a rebuilt
mesh is the only preview this operator has, since the planner's answer to a count, a shape
and a spacing is the same question -- can a strip be laid between these two rails.
"""

import bpy

from ..core import session as sessions
from ..i18n import pgettext
from ..operators import apply_counts, cut_notice, restore_source
from ..shape.state import (
    MODE_COUNT,
    MODE_EVEN,
    MODE_SMOOTH,
    ShapeController,
    strengthen,
)
from .hud import (
    clear_box_cache,
    clear_highlight_cache,
    draw_highlight,
    draw_hud,
    hide_notice,
    path_midpoint,
    segment_counts,
    show_notice,
)


_NAVIGATION_EVENTS = frozenset(
    {
        "MIDDLEMOUSE",
        "TRACKPADPAN",
        "TRACKPADZOOM",
        "MOUSEROTATE",
        "MOUSESMARTZOOM",
    }
)
_COMMIT_EVENTS = frozenset({"LEFTMOUSE"})
_CANCEL_EVENTS = frozenset({"RIGHTMOUSE"})
_WHEEL_UP = frozenset({"WHEELUPMOUSE", "WHEELINMOUSE"})
_WHEEL_DOWN = frozenset({"WHEELDOWNMOUSE", "WHEELOUTMOUSE"})
# Where the wheel was pointed when the session started: the entry counts, because the
# delta is relative to them, and neither strength moved.
_ENTRY_STATE = (0, 0.0, 0.0)


def _mode_for(shift_held, ctrl_held):
    """The axis the hands on the keyboard are pointing at, or the counts if none are.

    Shift wins when both are down.  While a session runs that tie cannot be reached --
    :meth:`_track_modifiers` arms whichever key just moved -- so it only settles the one
    case where both were already held on entry.
    """
    return MODE_SMOOTH if shift_held else MODE_EVEN if ctrl_held else MODE_COUNT


# The viewport the menu item was clicked in, remembered for the call the timer defers.
# Nothing else carries it: a timer callback runs without a UI context, so the deferred invoke
# has no area to ask, and guessing one from ``windows`` guesses the first one -- which with
# two Blender windows open on screen is the window the user is not in.
_MENU_CLICK = {"area": None}


def _clicked_viewport():
    """The remembered click's viewport, if it is still one on screen."""
    area = _MENU_CLICK["area"]
    if area is None:
        return None
    try:
        return area if area.type == "VIEW_3D" else None
    except ReferenceError:
        # Its window has been closed since the click.
        _MENU_CLICK["area"] = None
        return None


def _viewport_area(context):
    """The 3D viewport the overlay belongs to, even when the caller has no area to hand over.

    An operator invoked with the pointer in a viewport is handed that viewport as
    ``context.area``.  A call deferred out of a menu is not: its context carries a window but
    no area, and the overlay is pinned to the area captured here -- both draw handlers bail
    out whenever the area drawing them is not that pointer.  So a ``None`` here silences the
    whole readout while the wheel keeps rebuilding the mesh, which is what made the menu
    entry read as a dumber version of the same tool.

    The order is by how much is actually known.  The click is asked for second because the
    menu that deferred this call did know which viewport it was in, and the sweep over the
    screen's areas last because it does not: it returns whichever viewport comes first, and
    on a two-window desktop that is the other window's -- the overlay then reads as having
    jumped to the window the user is not scrolling in.
    """
    area = context.area
    if area is None or area.type != "VIEW_3D":
        area = _clicked_viewport()
    if area is None:
        window = context.window
        if window is None:
            for candidate in context.window_manager.windows:
                window = candidate
                break
        for candidate in getattr(getattr(window, "screen", None), "areas", ()):
            if candidate.type == "VIEW_3D":
                area = candidate
                break
    return area


def _show_refusal(context, error):
    """Put a refusal that came before any overlay existed onto the viewport.

    Called from ``invoke`` before anything has started, so there is no chip row to write
    into and ``self.report`` alone would leave the user staring at an unchanged viewport.

    Returns whether the sentence really landed in a viewport.  ``show_notice`` pins its draw
    handler to ``SpaceView3D`` and bails on a ``None`` area, so a call from a layout without
    one leaves nothing of ours on screen -- that is the only case where the caller still owes
    Blender a report, and the reason both channels are not simply one of them.
    """
    area = _viewport_area(context)
    if area is None or area.type != "VIEW_3D":
        return False
    show_notice(area, str(error))
    return True


class MESH_OT_loop_resample_interactive(bpy.types.Operator):
    """Scroll to set the locked paths' counts, shape and spacing, live."""

    bl_idname = "mesh.loop_resample_interactive"
    bl_label = "Adjust Resample by Wheel"
    bl_description = pgettext(
        "Lock the selection, then scroll to set its segment count.  Shift scrolls smooth "
        "the curve, Ctrl scrolls spread its points, and each tick strengthens that effect.  "
        "Left-click keeps it, right-click reverts."
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # No session required: the operator makes one.  The menu item runs this through a
        # forwarder, so a poll demanding a locked session would grey the item out before it
        # had ever done anything.
        #
        # Vertex or edge select mode only: the two modes a path is actually picked in.
        # This is a gate on the menu rather than a capability check -- the operator answers
        # to a selection made in either of those two, and points out on the mesh which part
        # of it it could not use.
        select_mode = context.tool_settings.mesh_select_mode
        return (
            context.mode == "EDIT_MESH"
            and context.active_object is not None
            and context.active_object.type == "MESH"
            and (select_mode[0] or select_mode[1])
        )

    def invoke(self, context, event):
        session = sessions.active(context)
        if session is None:
            # The lock that used to be its own click: the selection on
            # screen right now becomes the source, and the wheel works from there.
            try:
                session = sessions.begin(context)
            except ValueError as error:
                if not _show_refusal(context, error):
                    self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
        self.session = session
        self.entry_counts = list(session.counts)
        # A scroll carries every locked path by the same amount rather than driving them to
        # one shared number: paths of unequal length are a legitimate thing to have
        # locked, and an absolute target would silently rewrite the short one the moment
        # the wheel ticks.
        self.minimum_delta = min(
            (3 if closed else 2) - count
            for count, closed in zip(self.entry_counts, session.closed)
        )
        self.delta = 0
        # The two strength axes and which one the next tick belongs to.  The mode only
        # routes input: both strengths stay live whatever the mode says, so a step's
        # points are always the frozen source plus these three values and the order the
        # wheel was turned in cannot move one of them.  A strip's wiring is the one
        # exception, and a deliberate one -- see ``shape.state``.
        self.shape = ShapeController(session)
        self.t_smooth = 0.0
        self.t_even = 0.0
        # Whichever keys sit under the click that started this own the wheel from the
        # first tick, and are recorded as already seen so the next event cannot be read as
        # a fresh press of a key the hand was on anyway.
        self._modifiers_held = (bool(event.shift), bool(event.ctrl))
        self.mode = _mode_for(*self._modifiers_held)
        # The last strengths that reached a mesh, which is what the chips read.  A
        # refused step leaves the previous mesh standing, and a chip that moved
        # anyway would be describing a mesh that is not there.
        self.label_smooth = 0.0
        self.label_even = 0.0
        # The last thing the wheel was turned into, so a tick that changes nothing
        # rebuilds nothing -- including a refusal, which is the tick most likely to be
        # repeated because it is the one the operator can see did not work.
        self.attempted_state = None
        # The last thing that reached a mesh.  Distinct from the attempt above because a
        # refused step leaves the mesh standing at some earlier state, and the wheel has
        # to know that coming back to it is work rather than a no-op.
        self.applied_state = _ENTRY_STATE
        # The last refusal, or None: the wheel is allowed to stop working, but not
        # silently.  It stays up until a scroll succeeds again, so it cannot be missed.
        self.message = None
        self.label_values = tuple(session.counts)
        self.label_closed = tuple(session.closed)
        self.label_object = session.obj
        self._relabel(None)
        self.draw_handler = None
        self.highlight_handler = None
        hud_area = _viewport_area(context)
        self.hud_area = hud_area
        self.hud_area_ptr = hud_area.as_pointer() if hud_area else None
        self.labels_shown = False
        self.highlight_shown = False
        return self._start(context)

    def modal(self, context, event):
        self._tag_redraw(context)
        self._track_modifiers(event)

        if event.type in _CANCEL_EVENTS:
            # PRESS only, same reason as the commit below: a release on its own is not a
            # decision, and the clicks that end this operator are its press.
            if event.value == "PRESS":
                return self._cancel(context)
            return {"RUNNING_MODAL"}
        if event.type in _COMMIT_EVENTS:
            # PRESS only: the click that opened this operator ends
            # here as a RELEASE, and finishing on that would commit before a scroll starts.
            if event.value == "PRESS":
                return self._commit(context)
            return {"RUNNING_MODAL"}
        if event.type in _NAVIGATION_EVENTS:
            # Orbit and pan have to reach the view operator; the wheel above them is ours.
            return {"PASS_THROUGH"}

        if event.type in _WHEEL_UP:
            self._step(context, 1)
        elif event.type in _WHEEL_DOWN:
            self._step(context, -1)
        return {"RUNNING_MODAL"}

    def _track_modifiers(self, event):
        """Point the wheel at whichever key the hand moved last.

        Held, not latched: Shift keeps the shape axis armed for exactly as long as it is
        down and hands the wheel back to the counts on the way out, so nothing has to be
        remembered about which mode the session is in -- the two hands say.

        Read off every event rather than matched on its key name: ``event.shift`` is the
        one channel that cannot be missed, because a wheel tick carries the presses that
        were under it, so a scroll turned before a press event lands still lands on the
        axis that press asked for.
        """
        held = (bool(event.shift), bool(event.ctrl))
        if held == self._modifiers_held:
            return
        previous, self._modifiers_held = self._modifiers_held, held
        if held[0] and not previous[0]:
            self.mode = MODE_SMOOTH
        elif held[1] and not previous[1]:
            self.mode = MODE_EVEN
        else:
            # A key came up rather than going down.  The wheel goes to whichever one is
            # still held, so lifting the newer key hands it back to the older instead of
            # dropping the user off the axis they are still scrolling on.
            self.mode = _mode_for(*held)

    def cancel(self, context):
        """Blender ended the modal itself -- a mode switch, or another operator on top."""
        self._finish(context)

    def _step(self, context, delta):
        """Strengthen the armed axis one tick, then rebuild whatever the three values now say.

        The mode picks the axis and nothing else: both strengths stay live in every mode,
        so the wheel can be pointed at the smoothing, then at the counts, without the
        first one being forgotten on the way.

        The counts read the wheel the way Blender does, up adding a segment.  A strength
        axis reads it either way, because an axis that carries one function has no second
        direction to point at: a tick is one more step of the same effect whichever way
        the wheel turned, and the right-click that reverts the session is the only way
        back.  An axis that has already reached its end simply stops moving; the percentage
        on its chip is where the wheel says it stands, so nothing has to be said on top of
        it.
        """
        if self.mode == MODE_SMOOTH:
            stepped = strengthen(self.t_smooth)
            if stepped == self.t_smooth:
                return
            self.t_smooth = stepped
        elif self.mode == MODE_EVEN:
            stepped = strengthen(self.t_even)
            if stepped == self.t_even:
                return
            self.t_even = stepped
        else:
            self.delta = max(self.minimum_delta, self.delta + delta)
        self._apply(context)

    def _apply(self, context):
        """Rebuild at the current three values, unless that is what is already standing.

        A step the planner cannot solve leaves the previous mesh in place, and the number
        on screen not moving is only half the report: the other half is the reason, because
        a wheel that does nothing with nothing said is indistinguishable from a wheel that
        is not being heard.
        """
        state = (self.delta, self.t_smooth, self.t_even)
        if state == self.attempted_state:
            return
        self.attempted_state = state
        if state == self.applied_state:
            # Back on the mesh that is already there -- only reachable after a refusal
            # took the wheel somewhere else and a scroll brought it back.  The notice
            # about that refusal describes a count that is no longer being asked for.
            self.message = None
            return
        counts = [entry + self.delta for entry in self.entry_counts]
        frame = self.shape.frame(self.t_smooth, self.t_even)
        succeeded, message = apply_counts(context, self.session, counts, shape=frame)
        if succeeded:
            self.applied_state = state
            self.label_values = tuple(counts)
            self.label_smooth = self.t_smooth
            self.label_even = self.t_even
            self.message = None
            self._relabel(frame)
        else:
            self.message = message

    def _relabel(self, frame):
        """Put the numbers on the curve this step laid the mesh down on.

        Anchored to the moved points rather than to the frozen source, because a path
        whose control points moved has left the source behind by as much as the
        smoothing's own displacement, and a number that stayed where the source was
        would be labelling empty space.

        Still once per step rather than per redraw: like the source anchor it replaces, this
        cannot hop while the counts roll, because a frame depends on the strengths alone.
        """
        anchors = (
            self.shape.source_points
            if frame is None
            else tuple(
                source if moved is None else moved
                for source, moved in zip(self.shape.source_points, frame.points)
            )
        )
        self.label_points = tuple(
            path_midpoint(points, closed)
            for points, closed in zip(anchors, self.label_closed)
        )

    def _restore_entry(self, context):
        """Put back the mesh the wheel found: the locked source, written back as it stands.

        This is deliberately not a step at the entry counts.  A step re-solves, and the
        re-solve has no reason to reproduce the source's own wiring -- measured on a ring
        whose bands are 8x8 and 8x12, an entry-count step landed every vertex back on its
        source position and still moved 11 of the 20 rebuilt faces.  The session already
        holds the source the steps rebuild from, so reverting is that copy put back, and
        the counts, the shape and the selection come with it for nothing.
        """
        if self.applied_state == _ENTRY_STATE:
            return True, "Left the curve as it was."
        moved_shape = self.applied_state[1:] != (0.0, 0.0)
        restore_source(context, self.session, self.entry_counts)
        self.applied_state = _ENTRY_STATE
        self.attempted_state = _ENTRY_STATE
        self.label_values = tuple(self.entry_counts)
        self.label_smooth = 0.0
        self.label_even = 0.0
        self._relabel(None)
        counts = ", ".join(
            str(value)
            for value in segment_counts(self.session.counts, self.label_closed)
        )
        template = (
            "Reverted to {counts} segment(s) and the original curve."
            if moved_shape
            else "Reverted to {counts} segment(s)."
        )
        return True, pgettext(template).format(counts=counts)

    def _commit(self, context):
        # Read before finishing: finishing ends the session, and the report is the last
        # thing this operator says about it.
        kept = ", ".join(
            str(value)
            for value in segment_counts(self.session.counts, self.label_closed)
        )
        strengthened = self.applied_state[1:] != (0.0, 0.0)
        note = cut_notice(self.session)
        self._finish(context)
        template = (
            "Kept {counts} segment(s) and the adjusted curve on the locked path(s)."
            if strengthened
            else "Kept {counts} segment(s) on the locked path(s)."
        )
        self.report({"INFO"}, pgettext(template).format(counts=kept) + note)
        return {"FINISHED"}

    def _cancel(self, context):
        succeeded, message = self._restore_entry(context)
        self._finish(context)
        self.report({"INFO" if succeeded else "ERROR"}, message)
        return {"CANCELLED"}

    def _start(self, context):
        # A notice from the click before this one has nothing left to explain: this one got
        # as far as starting, and the chip row takes over the reporting from here.
        hide_notice()
        self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            draw_hud,
            (self, context),
            "WINDOW",
            "POST_PIXEL",
        )
        # A second handler one phase earlier for the outline around the paths: that one is
        # world-space geometry and has to reach the depth buffer to match the mesh.
        self.highlight_handler = bpy.types.SpaceView3D.draw_handler_add(
            draw_highlight,
            (self, context),
            "WINDOW",
            "POST_VIEW",
        )
        self.labels_shown = True
        self.highlight_shown = True
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def _finish(self, context):
        self.labels_shown = False
        self.highlight_shown = False
        if self.draw_handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, "WINDOW")
            self.draw_handler = None
        if self.highlight_handler is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self.highlight_handler, "WINDOW")
            self.highlight_handler = None
        clear_box_cache()
        clear_highlight_cache()
        # The session ends with the scroll that owns it, both ways out: a frozen source
        # left behind is memory held for nothing, and worse, the next right-click would
        # find it and keep adjusting the mesh from the selection that was
        # current two tools ago.
        sessions.end(context)
        self._tag_redraw(context)

    def _tag_redraw(self, context):
        """Refresh the view this modal started in, and the one answering now if different."""
        seen = set()
        for area in (self.hud_area, context.area):
            if area is None:
                continue
            try:
                pointer = area.as_pointer()
            except ReferenceError:
                continue
            if pointer not in seen:
                seen.add(pointer)
                area.tag_redraw()


def _start_wheel_modal():
    """Ask for the wheel from outside the menu that asked for it.

    ``None`` retires the timer; this fires once.
    """
    try:
        bpy.ops.mesh.loop_resample_interactive("INVOKE_DEFAULT")
    except RuntimeError as error:
        # The selection can stop answering the poll between the click and this callback --
        # the menu closing is not a commit, but it is a redraw, and a viewport that lost the
        # mesh in between has nothing left to lock.  A timer callback has no operator to
        # report through, so the only channel left is the console; silence here is what read
        # as "the menu item does nothing" the first time round.
        print(f"[Loop Resample][diagnostic] menu entry could not start the wheel: {error}")
    return None


class MESH_OT_loop_resample_interactive_entry(bpy.types.Operator):
    """Forward one menu click to the wheel modal, one pass of the loop later.

    The right-click menu cannot call :class:`MESH_OT_loop_resample_interactive` itself.  A
    modal handler is attached to the region the operator was invoked in, and for an item
    picked out of a menu that region is the menu's own popup -- which is torn down as soon
    as the item fires.  The handler dies with it, Blender then calls ``cancel()`` on the
    operator, and ``cancel()`` ends the session with the mesh untouched.  That is the exact
    shape of "nothing happened": no error, no overlay, no wheel.

    Deferred by a timer, the popup is gone and the context is the viewport again -- the same
    condition that makes a call from the Python console work.
    """

    bl_idname = "mesh.loop_resample_interactive_entry"
    bl_label = "Adjust Loops by Wheel"
    # Not a thing to search for: the operator it forwards to is the one that belongs in the
    # list, and two entries worded identically would read as one of them being broken.
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return MESH_OT_loop_resample_interactive.poll(context)

    def execute(self, context):
        # This much is known here and nowhere later: the menu runs with the clicked viewport
        # as its area, while the deferred invoke will not have one at all.
        _MENU_CLICK["area"] = context.area
        # Guarded the way the session watcher guards its own: a second click before the
        # first callback runs would otherwise register the same function twice.
        if not bpy.app.timers.is_registered(_start_wheel_modal):
            bpy.app.timers.register(_start_wheel_modal, first_interval=0.0)
        return {"FINISHED"}

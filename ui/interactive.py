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

The sidebar button runs this operator directly, which makes the operator responsible for
both ends of the life: it locks the mesh on the way in -- the panel used to do that, in a
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
from ..operators import apply_counts, restore_source
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
    path_midpoint,
    segment_counts,
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


class MESH_OT_loop_resample_interactive(bpy.types.Operator):
    """Scroll to set the locked paths' counts, shape and spacing, live."""

    bl_idname = "mesh.loop_resample_interactive"
    bl_label = "Adjust Resample by Wheel"
    bl_description = (
        "Lock what is selected, then scroll to set its segment count.  Hold Shift and "
        "scroll to smooth the locked curve(s), or Ctrl and scroll to spread their points "
        "more evenly -- every tick strengthens whichever effect the held key armed, and "
        "left-click keeps it while right-click goes back to what was there before"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # No session required: the operator makes one.  The panel has a single button that
        # runs this, so a poll demanding a locked session would grey the button out before
        # it had ever done anything.
        return (
            context.mode == "EDIT_MESH"
            and context.active_object is not None
            and context.active_object.type == "MESH"
        )

    def invoke(self, context, event):
        session = sessions.active(context)
        if session is None:
            # The lock that the sidebar used to do in its own click: the selection on
            # screen right now becomes the source, and the wheel works from there.
            try:
                session = sessions.begin(context)
            except ValueError as error:
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
        self.hud_area = context.area
        self.hud_area_ptr = context.area.as_pointer() if context.area else None
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
            # PRESS only: the click that launched this operator from the sidebar ends
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
        back.  An axis already at full strength says so instead of stopping dead, which
        is the whole difference between a finished control and a broken one.
        """
        if self.mode == MODE_SMOOTH:
            stepped = strengthen(self.t_smooth)
            if stepped == self.t_smooth:
                # The axis has one end and the wheel has already reached it: saying so is
                # the whole difference between a finished control and a broken one.
                self.message = "Curve smoothing is already at full strength."
                return
            self.t_smooth = stepped
        elif self.mode == MODE_EVEN:
            stepped = strengthen(self.t_even)
            if stepped == self.t_even:
                self.message = "Point spacing is already as even as it gets."
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
        return (
            True,
            "Reverted to "
            + ", ".join(
                str(value)
                for value in segment_counts(self.session.counts, self.label_closed)
            )
            + " segment(s)"
            + (" and the original curve" if moved_shape else "")
            + ".",
        )

    def _commit(self, context):
        # Read before finishing: finishing ends the session, and the report is the last
        # thing this operator says about it.
        kept = ", ".join(
            str(value)
            for value in segment_counts(self.session.counts, self.label_closed)
        )
        strengthened = self.applied_state[1:] != (0.0, 0.0)
        self._finish(context)
        self.report(
            {"INFO"},
            "Kept "
            + kept
            + " segment(s)"
            + (" and the adjusted curve" if strengthened else "")
            + " on the locked path(s).",
        )
        return {"FINISHED"}

    def _cancel(self, context):
        succeeded, message = self._restore_entry(context)
        self._finish(context)
        self.report({"INFO" if succeeded else "ERROR"}, message)
        return {"CANCELLED"}

    def _start(self, context):
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
        # left behind is memory held for nothing, and worse, the next click on the
        # sidebar would find it and keep adjusting the mesh from the selection that was
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

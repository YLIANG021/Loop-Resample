"""Scroll-to-set interaction for a resample session it starts itself.

The wheel steps the counts and rebuilds the mesh once per step, not per event; the rebuild
is the only preview.  Shift arms smoothing, Ctrl arms evening out the points, and both are
one-way: a tick strengthens whichever way the wheel turns, and only right-click reverts.  No
key confirms or cancels.  Nothing reads the mouse position: a sideways drag turns a view
navigation into a hundred new points.  The counts are painted on their path, not into a box
mid-screen, and refused steps go onto the overlay; a silent scroll reads as a broken wheel.
The menu uses a forwarder, so the operator locks the mesh on the way in and drops the
session on the way out; a session must not outlive its scroll.
"""

import bpy

from ..core import session as sessions
from ..core.diagnostics import enabled
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
# Where the wheel started: the entry counts, the delta being relative to them, and neither
# strength moved.
_ENTRY_STATE = (0, 0.0, 0.0)


def _mode_for(shift_held, ctrl_held):
    """MODE_SMOOTH under Shift, MODE_EVEN under Ctrl, counts under neither.

    Shift wins when both are down.  During a session that tie cannot be reached, because
    _track_modifiers arms whichever key just moved, so this only settles the case where
    both were already held on entry.
    """
    return MODE_SMOOTH if shift_held else MODE_EVEN if ctrl_held else MODE_COUNT


# The viewport the menu item was clicked in, for the timer-deferred invoke: a timer
# callback runs without a UI context, so the deferred call has no area to ask, and
# picking from ``windows`` takes the first, which on a two-window desktop is the one the
# user is not in.
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
    """The 3D viewport the overlay draws into, or None.

    A pointer invoke gets its viewport as ``context.area``.  A call deferred from a menu
    gets a window and no area, and both draw handlers bail out unless the area drawing
    them is the one captured here.  Returning None would leave the wheel rebuilding the
    mesh with nothing on screen to show for it.

    The fallbacks go by how much is known: the remembered click before the screen sweep,
    because the deferring menu knew its viewport, while the sweep takes whichever viewport
    comes first, and on a two-window desktop that is the other window's.
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
    """Put a pre-overlay refusal onto the viewport; return whether it landed.

    Called from ``invoke`` before anything has started, so there is no chip row to write
    into and ``self.report`` alone would leave the user staring at an unchanged viewport.
    ``show_notice`` pins its draw handler to ``SpaceView3D`` and bails on a None area, so
    from a layout without a viewport nothing reaches the screen: the only case where the
    caller still owes Blender a report, and the reason there are two channels.
    """
    area = _viewport_area(context)
    if area is None or area.type != "VIEW_3D":
        return False
    show_notice(area, str(error))
    return True


# The two menu tooltips, kept in English on purpose.  Blender translates an operator's
# description itself when it draws the hover text, through the same ``("*", sentence)``
# table the overlay reads, so these follow the interface language, changes included.
# Running them through ``pgettext`` here instead would freeze them in the language set
# when the add-on loaded: the description is read off the class once, at registration.
_TOOLTIP_MAIN = (
    "Lock the selection, then scroll to set its segment count.  Shift scrolls smooth "
    "the curve, Ctrl scrolls spread its points, and each tick strengthens that effect.  "
    "Left-click keeps it, right-click reverts."
)
_TOOLTIP_ENTRY = (
    "Quickly adjust the segment count of any edge:  scroll sets the count, Shift "
    "smooths the edge, Ctrl spreads the points evenly, and attributes such as "
    "UVs, seams and vertex colors survive the change intact."
)


class MESH_OT_loop_resample_interactive(bpy.types.Operator):
    """Scroll to set the locked paths' counts, shape and spacing, live."""

    bl_idname = "mesh.loop_resample_interactive"
    bl_label = "Adjust Resample by Wheel"
    bl_description = _TOOLTIP_MAIN
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # No session required: the operator makes one, and a poll demanding a locked
        # session would grey out the menu item behind the forwarder before it ever ran.
        #
        # Vertex or edge select mode only, the two modes a path is actually picked in.
        # This gates the menu rather than checking a capability: the operator answers to
        # a selection made in either and points out on the mesh which part of it it could
        # not use.
        select_mode = context.tool_settings.mesh_select_mode
        available = (
            context.mode == "EDIT_MESH"
            and context.active_object is not None
            and context.active_object.type == "MESH"
            and (select_mode[0] or select_mode[1])
        )
        if not available:
            # One message for all four failures: the user can see which of the four it
            # was.  The forwarder's poll calls this, so the menu item gets it too.
            cls.poll_message_set(
                pgettext(
                    "Only available in mesh Edit Mode, with the vertex or edge "
                    "select mode turned on."
                )
            )
        return available

    def invoke(self, context, event):
        session = sessions.active(context)
        if session is None:
            # The lock that used to be its own click: the current selection becomes the
            # source.
            try:
                session = sessions.begin(context)
            except ValueError as error:
                if not _show_refusal(context, error):
                    self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
        self.session = session
        self.entry_counts = list(session.counts)
        # Every locked path moves by the same delta rather than to one shared number:
        # paths of unequal length are legitimately locked together, and an absolute
        # target would silently rewrite the short one on the first tick.
        self.minimum_delta = min(
            (3 if closed else 2) - count
            for count, closed in zip(self.entry_counts, session.closed)
        )
        self.delta = 0
        # The mode only routes input: both strengths stay live whatever it says, so a
        # step's points are always the frozen source plus these three values, and the
        # order the wheel was turned in cannot move one of them.  A strip's wiring is
        # the one exception, deliberate; see ``shape.state``.
        self.shape = ShapeController(session)
        self.t_smooth = 0.0
        self.t_even = 0.0
        # Keys already down for the click that started this own the wheel from the first
        # tick, and are recorded as seen so the next event cannot read as a fresh press.
        self._modifiers_held = (bool(event.shift), bool(event.ctrl))
        self.mode = _mode_for(*self._modifiers_held)
        # The last strengths that reached a mesh, which is what the chips read: a refused
        # step leaves the previous mesh standing, and a chip that moved anyway would
        # describe a mesh that is not there.
        self.label_smooth = 0.0
        self.label_even = 0.0
        # The last thing the wheel was turned into, so a tick that changes nothing
        # rebuilds nothing.  Refusals count: the operator can see that tick did not
        # work, so it is the one most likely to be repeated.
        self.attempted_state = None
        # The last thing that reached a mesh.  Distinct from the attempt above: after a
        # refusal the mesh stands at an earlier state, and coming back to it is work
        # rather than a no-op.
        self.applied_state = _ENTRY_STATE
        # The last refusal, or None.  The wheel may stop working but not silently; this
        # stays up until a scroll succeeds again.
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
            # decision.
            if event.value == "PRESS":
                return self._cancel(context)
            return {"RUNNING_MODAL"}
        if event.type in _COMMIT_EVENTS:
            # PRESS only: the click that opened this operator ends here as a RELEASE, and
            # finishing on that would commit before a scroll starts.
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

        Held, not latched: an axis stays armed exactly as long as its key is down, then
        the wheel goes back to the counts; no mode has to be remembered.

        Read off every event rather than matched on its key name: a wheel tick carries
        the presses that were under it, so ``event.shift`` is the one channel that cannot
        be missed, and a scroll turned before a press event lands still lands on the axis
        that press asked for.
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
        """Blender ended the modal itself: a mode switch, or another operator on top."""
        self._finish(context)

    def _step(self, context, delta):
        """Strengthen the armed axis one tick, then rebuild whatever the three values now say.

        The mode picks the axis and nothing else: both strengths stay live, so pointing
        the wheel at the smoothing and then at the counts does not forget the first.

        The counts read the wheel the way Blender does, up adding a segment.  A strength
        axis reads it either way, having no second direction to point at: a tick is one
        more step of the same effect whichever way the wheel turned, and the right-click
        that reverts the session is the only way back.  An axis that reaches its end
        stops moving; the percentage on its chip says where it stands.
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
        on screen not moving is only half the report: the other half is the reason,
        because a wheel that silently does nothing looks exactly like one that is not
        being heard.
        """
        state = (self.delta, self.t_smooth, self.t_even)
        if state == self.attempted_state:
            return
        self.attempted_state = state
        if state == self.applied_state:
            # Back on the mesh that is already there, reachable only after a refusal took
            # the wheel somewhere else and a scroll brought it back.  That refusal's
            # notice describes a count that is no longer being asked for.
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

        Anchored to the moved points rather than to the frozen source: smoothing
        displaces the control points, and a number that stayed where the source was
        would be labelling empty space.

        Once per step rather than per redraw: a frame depends on the strengths alone,
        so it cannot hop while the counts roll.
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

        Deliberately not a step at the entry counts.  A step re-solves, and the re-solve
        has no reason to reproduce the source's own wiring: measured on a ring whose
        bands are 8x8 and 8x12, an entry-count step landed every vertex back on its
        source position and still moved 11 of the 20 rebuilt faces.  The session already
        holds the source the steps rebuild from, so reverting is that copy put back, and
        the counts, the shape and the selection come along.
        """
        if self.applied_state == _ENTRY_STATE:
            return True, pgettext("Left the curve as it was.")
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
        # Read before finishing: _finish ends the session, and the report is the
        # operator's last word on it.
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
        # The previous click's notice is stale: this one started, and the chip row takes
        # over the reporting from here.
        hide_notice()
        self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(
            draw_hud,
            (self, context),
            "WINDOW",
            "POST_PIXEL",
        )
        # A second handler one phase earlier for the path outline: world-space geometry,
        # which has to reach the depth buffer to match the mesh.
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
        # The session ends with the scroll that owns it, both ways out: a leftover
        # frozen source is memory held for nothing, and the next right-click would find
        # it and adjust the mesh from a selection two tools old.
        sessions.end()
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
    """Invoke the wheel from outside the menu that asked for it.

    ``None`` retires the timer; this fires once.
    """
    try:
        bpy.ops.mesh.loop_resample_interactive("INVOKE_DEFAULT")
    except RuntimeError as error:
        # The selection can stop answering the poll between the click and this callback:
        # the menu closing is not a commit, but it is a redraw, and a viewport that lost
        # the mesh in between has nothing left to lock.  A timer callback has no operator
        # to report through, so the notice pinned to the clicked viewport is the only
        # channel left; silence here once read as "the menu item does nothing".
        area = _clicked_viewport()
        if area is not None:
            show_notice(
                area,
                pgettext(
                    "The wheel could not start: this viewport no longer has a mesh to adjust."
                ),
            )
        if enabled():
            print(f"[Loop Resample][diagnostic] menu entry lost the viewport: {error}")
    return None


class MESH_OT_loop_resample_interactive_entry(bpy.types.Operator):
    """Forward one menu click to the wheel modal, one pass of the loop later.

    The right-click menu cannot call MESH_OT_loop_resample_interactive itself.  A modal
    handler attaches to the region the operator was invoked in; for a menu item that is
    the menu's own popup, torn down as soon as the item fires.  The handler dies with
    it, Blender calls ``cancel()``, and the session ends with the mesh untouched: no
    error, no overlay, no wheel.

    Deferred by a timer, the popup is gone and the context is the viewport again, the
    same condition that makes a call from the Python console work.

    The rule against wrapper operators is about re-wrapping Blender's own so a user can
    reach them from a panel; nothing native does what this forwards to, and the class
    exists only because a menu popup cannot host a modal handler.
    """

    bl_idname = "mesh.loop_resample_interactive_entry"
    # The product name, untranslated on purpose: it has no i18n entry, so every locale
    # gets the English.  The tooltip below is the one that gets localized.
    bl_label = "Loop Resample"
    # Without this the class docstring would surface as the menu's hover text, and that
    # is about the deferred invoke rather than about what the tool does.
    bl_description = _TOOLTIP_ENTRY
    # Not searchable: the operator it forwards to is the one that belongs in the list,
    # and two entries worded identically would read as one being broken.
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context):
        return MESH_OT_loop_resample_interactive.poll(context)

    def execute(self, context):
        # Known here and nowhere later: the menu runs with the clicked viewport as its
        # area, while the deferred invoke will not have one.
        _MENU_CLICK["area"] = context.area
        # A second click before the first callback runs would otherwise register the
        # same function twice and invoke the wheel twice.
        if not bpy.app.timers.is_registered(_start_wheel_modal):
            bpy.app.timers.register(_start_wheel_modal, first_interval=0.0)
        return {"FINISHED"}

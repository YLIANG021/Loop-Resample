"""Curve shape and distribution axes for Loop Resample.

Deliberately imports nothing: ``core.curves`` reads the measure helpers in ``.warp``
and the entry point imports ``core.curves`` back, so a re-export here would be an
import cycle.  Callers name the module they want.
"""

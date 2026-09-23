"""Curve shape and distribution axes for Loop Resample.

Deliberately imports nothing: ``core.curves`` reads the measure helpers in
:mod:`.warp`, and this package's own entry point imports ``core.curves`` back, so a
re-export here would be a cycle waiting for an import order to trip over.  Callers
name the module they want.
"""

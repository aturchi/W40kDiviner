"""Spec-driven Tkinter forms.

build_form(frame, fields, data) creates one row of widgets per field
spec and returns the (key, kind, var, widget) list; apply_form writes the
widget values back into data. Field specs are tuples
(data_key, kind, label, options) as used by condition_specs and
effect_specs. Data keys not covered by the spec are left untouched.

A CHOICE is stored as {"title": ..., "key": ...}: the KEY is what the
engine reads, the title is only what the combobox shows. The two are
resolved key-first, in both directions, so that improving a spec LABEL
never has to be a data migration - a roster saved with the old wording
keeps working, the form shows the new wording, and what the ability
DOES does not move. Nothing here raises on a value the spec no longer
knows: an unreadable stored choice falls back on the spec default,
which is the same value a freshly created one would get.
"""

import tkinter as tk
from tkinter import ttk

from spec_kinds import CHOICE, ENUM, BOOL, KEYWORDS, COMBO


def _same_key(a, b) -> bool:
    """Keys compare case-insensitively, the way modifier_engine._key
    reads them, so a hand-written roster is not held to the exact
    casing of the spec."""
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def choice_title(options, value) -> str:
    """The label to show for a stored CHOICE.

    Resolved by KEY first, by title second. That order is the whole
    point: a spec label can be corrected and the old rosters follow,
    because the key they carry still names the same option."""
    if isinstance(value, dict):
        for title, key in options:
            if _same_key(key, value.get("key")):
                return title
        stored = value.get("title")
    else:
        stored = value if isinstance(value, str) else None
    for title, _key in options:
        if title == stored:
            return title
    return options[0][0] if options else ""


def choice_value(options, title, previous=None) -> dict:
    """The {"title", "key"} to store for a chosen label.

    'previous' is what was there before. The combobox is read-only and
    seeded from the spec, so an unknown title only happens for a stored
    value the spec no longer knows - and then the KEY is kept if it is
    still a valid one, because a label that changed must not silently
    change what the ability does."""
    for t, k in options:
        if t == title:
            return {"title": t, "key": k}
    prev = previous if isinstance(previous, dict) else {}
    for t, k in options:
        if _same_key(k, prev.get("key")):
            return {"title": t, "key": k}
    return {"title": options[0][0], "key": options[0][1]} if options else {}


def build_form(frame, fields, data, start_row=0):
    """Lay out a label+widget form for 'fields' into 'frame', bound to 'data'; returns the widgets keyed by field name."""
    fvars = []
    for row, (key, kind, label, options) in enumerate(fields, start=start_row):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W,
                                          padx=4, pady=2)
        value = data.get(key)
        if kind == CHOICE:
            var = tk.StringVar(value=choice_title(options, value))
            widget = ttk.Combobox(frame, textvariable=var, state="readonly",
                                  width=30, values=[t for t, _k in options])
            widget.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        elif kind == ENUM:
            var = tk.StringVar(value=value or "")
            widget = ttk.Combobox(frame, textvariable=var, state="readonly",
                                  width=30, values=options)
            widget.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        elif kind == BOOL:
            var = tk.BooleanVar(value=bool(value))
            widget = ttk.Checkbutton(frame, variable=var)
            widget.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        elif kind == KEYWORDS:
            var = tk.StringVar(value=", ".join(value or []))
            widget = ttk.Entry(frame, textvariable=var, width=33)
            widget.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        elif kind == COMBO:
            # Editable combobox: suggestions from options, free text allowed
            # (e.g. parametric keywords like 'SUSTAINED HITS 2')
            var = tk.StringVar(value="" if value is None else str(value))
            widget = ttk.Combobox(frame, textvariable=var, values=options,
                                  width=30)
            widget.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        else:  # TEXT
            var = tk.StringVar(value="" if value is None else str(value))
            widget = ttk.Entry(frame, textvariable=var, width=33)
            widget.grid(row=row, column=1, sticky=tk.W, padx=4, pady=2)
        fvars.append((key, kind, var, widget))
    return fvars


def apply_form(fvars, fields, data):
    """Write widget values back into data (CHOICE -> {title,key}).

    Never raises on a stored choice the spec no longer knows: see
    choice_value for what happens instead."""
    optmap = {key: options for key, _kind, _label, options in fields}
    for key, kind, var, *_ in fvars:
        if kind == CHOICE:
            data[key] = choice_value(optmap.get(key) or (), var.get(),
                                     data.get(key))
        elif kind == BOOL:
            data[key] = bool(var.get())
        elif kind == KEYWORDS:
            data[key] = [s.strip().upper() for s in var.get().split(",")
                         if s.strip()]
        else:  # ENUM / TEXT
            data[key] = var.get()

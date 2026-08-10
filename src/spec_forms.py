"""Spec-driven Tkinter forms.

build_form(frame, fields, data) creates one row of widgets per field
spec and returns the (key, kind, var, widget) list; apply_form writes the
widget values back into data. Field specs are tuples
(data_key, kind, label, options) as used by condition_specs and
effect_specs. Data keys not covered by the spec are left untouched.
"""

import tkinter as tk
from tkinter import ttk

from spec_kinds import CHOICE, ENUM, BOOL, KEYWORDS, COMBO


def build_form(frame, fields, data, start_row=0):
    """Lay out a label+widget form for 'fields' into 'frame', bound to 'data'; returns the widgets keyed by field name."""
    fvars = []
    for row, (key, kind, label, options) in enumerate(fields, start=start_row):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W,
                                          padx=4, pady=2)
        value = data.get(key)
        if kind == CHOICE:
            var = tk.StringVar(value=(value or {}).get("title", ""))
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
    Raises KeyError on an unknown CHOICE title."""
    optmap = {key: options for key, _kind, _label, options in fields}
    for key, kind, var, *_ in fvars:
        if kind == CHOICE:
            title = var.get()
            data[key] = {"title": title, "key": dict(optmap[key])[title]}
        elif kind == BOOL:
            data[key] = bool(var.get())
        elif kind == KEYWORDS:
            data[key] = [s.strip().upper() for s in var.get().split(",")
                         if s.strip()]
        else:  # ENUM / TEXT
            data[key] = var.get()

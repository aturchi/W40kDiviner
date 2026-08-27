"""A minimal, in-memory stand-in for tkinter / tkinter.ttk.

Enough of the API to instantiate the project's widgets and drive them:
Treeview keeps a real item tree, Entry a real text buffer, bind() stores
callbacks so events can be fired by hand. Nothing is drawn, no display is
needed, and no window ever appears.

WHAT THIS IS FOR. Tkinter is in the standard library, but it is an
OPTIONAL build: a stripped-down Python (a slim container, a distribution
without python3-tk) has no tkinter at all, and every GUI test then fails
for a reason that has nothing to do with the code under test. The stub
lets those tests still exercise real widget logic - callback wiring,
column alignment, selection handling - which is how several real bugs in
this project were found.

HOW TO USE IT. Call :func:`install_if_missing` at the top of a test,
BEFORE importing any GUI module::

    import testpaths                  # noqa: F401
    import tkstub
    tkstub.install_if_missing()
    import unit_tree

It is a FALLBACK, never a substitute. When the real tkinter is present it
does nothing at all and the test runs against the real thing, because a
stub that shadowed a working tkinter would let the suite pass while the
program was broken. When it does step in it says so on stdout, so a green
run can never quietly mean "green against a fake".

THE ONE CASE IT DOES NOT COVER. The criterion is whether the tkinter
PACKAGE imports, not whether a display exists. On a machine that has
tkinter but no X/Wayland session, ``import tkinter`` succeeds and
``Tk()`` then raises TclError - a different failure, deliberately left
visible rather than hidden behind the stub. A test that needs a real
window (test_hist_canvas) therefore tries ``Tk()`` itself and calls
:func:`install` on failure, saying so on stdout.

READING BACK WHAT WAS DRAWN. Canvas records its items and exposes them
through Tk's OWN accessors - find_all / type / coords / itemcget /
bbox - and the font module keeps a real named-font registry with Tk's
delete-on-collect behaviour. Both exist so that a test can be written
against the real API and run unchanged on either toolkit. Reaching for
a stub attribute instead is how a test once passed headless and failed
on a machine with a display.
"""
import sys
import types

# --- constants -----------------------------------------------------------
END = "end"
LEFT, RIGHT, TOP, BOTTOM = "left", "right", "top", "bottom"
X, Y, BOTH, NONE = "x", "y", "both", "none"
W, E, N, S, CENTER = "w", "e", "n", "s", "center"
NW, NE, SW, SE = "nw", "ne", "sw", "se"
VERTICAL, HORIZONTAL = "vertical", "horizontal"
EXTENDED, BROWSE, SINGLE = "extended", "browse", "single"
NORMAL, DISABLED, ACTIVE = "normal", "disabled", "active"
WORD, CHAR = "word", "char"
FLAT, RAISED, SUNKEN, GROOVE, RIDGE, SOLID = (
    "flat", "raised", "sunken", "groove", "ridge", "solid")
INSERT, ANCHOR, SEL_FIRST, SEL_LAST = "insert", "anchor", "sel.first", "sel.last"
TclError = type("TclError", (Exception,), {})


class Variable:
    def __init__(self, master=None, value=None, name=None):
        self._v = value if value is not None else self._default
        self._traces = []

    _default = None

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in self._traces:
            cb()

    def trace_add(self, mode, cb):
        self._traces.append(lambda *a: cb(None, None, mode))

    trace = trace_add


class StringVar(Variable):
    _default = ""


class IntVar(Variable):
    _default = 0


class BooleanVar(Variable):
    _default = False


class DoubleVar(Variable):
    _default = 0.0


class Misc:
    """Base widget: geometry managers, options, bindings, scheduling."""

    def __init__(self, master=None, **kw):
        self.master = master
        self._opts = dict(kw)
        self._children = []
        self._binds = {}
        self._packed = False
        if isinstance(master, Misc):
            master._children.append(self)

    # -- options
    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        self._opts.update(kw)
        return self._opts

    config = configure

    def cget(self, key):
        return self._opts.get(key)

    def __getitem__(self, key):
        return self._opts.get(key)

    def __setitem__(self, key, value):
        self._opts[key] = value

    def keys(self):
        return list(self._opts)

    # -- geometry
    def pack(self, **kw):
        self._packed = True

    def grid(self, **kw):
        self._packed = True

    def place(self, **kw):
        self._packed = True

    def pack_forget(self):
        self._packed = False

    grid_forget = place_forget = pack_forget

    def pack_propagate(self, *a):
        pass

    def grid_columnconfigure(self, *a, **k):
        pass

    grid_rowconfigure = columnconfigure = rowconfigure = grid_columnconfigure

    def winfo_children(self):
        return list(self._children)

    def winfo_exists(self):
        return True

    def winfo_width(self):
        return 400

    winfo_height = winfo_reqwidth = winfo_reqheight = winfo_width

    def winfo_rootx(self):
        return 0

    winfo_rooty = winfo_x = winfo_y = winfo_rootx

    def winfo_toplevel(self):
        m = self
        while isinstance(m.master, Misc):
            m = m.master
        return m

    # -- events
    def bind(self, seq=None, func=None, add=None):
        """Bind, or - called bare - report what is bound, which is what
        the real Misc.bind does and the only way a test can ask the
        question without reaching into this stub."""
        if seq is None:
            return tuple(self._binds)
        self._binds.setdefault(seq, []).append(func)
        return "stub-funcid"

    bind_all = bind_class = bind

    def unbind(self, seq, funcid=None):
        self._binds.pop(seq, None)

    def event_generate(self, seq, **kw):
        ev = types.SimpleNamespace(widget=self, **kw)
        for f in list(self._binds.get(seq, [])):
            f(ev)

    fire = event_generate

    def after(self, ms, func=None, *a):
        if func:
            func(*a)
        return "id"

    def after_idle(self, func=None, *a):
        return self.after(0, func, *a)

    def after_cancel(self, i):
        pass

    def focus_set(self):
        pass

    focus = focus_force = focus_set

    def focus_get(self):
        return None

    def update(self):
        pass

    update_idletasks = update

    def destroy(self):
        if isinstance(self.master, Misc) and self in self.master._children:
            self.master._children.remove(self)

    def clipboard_clear(self):
        pass

    def clipboard_append(self, s):
        pass

    def selection_clear(self, **k):
        pass


class Tk(Misc):
    def __init__(self, *a, **kw):
        Misc.__init__(self, None, **kw)

    def title(self, *a):
        pass

    def geometry(self, *a):
        pass

    def minsize(self, *a):
        pass

    maxsize = resizable = minsize

    def overrideredirect(self, *a):
        """Undecorated window (tooltips). No-op here: the stub has no
        window manager to tell."""

    def attributes(self, *a):
        pass

    wm_overrideredirect = overrideredirect
    wm_attributes = attributes
    wm_geometry = geometry
    wm_title = title

    def protocol(self, *a):
        pass

    def mainloop(self):
        pass

    def iconphoto(self, *a):
        pass

    def withdraw(self):
        pass

    deiconify = lift = withdraw

    def wait_window(self, *a):
        pass

    def transient(self, *a):
        pass

    def grab_set(self, *a):
        pass

    grab_release = grab_set

    def state(self, *a):
        return "normal"

    def attributes(self, *a):
        pass

    def columnconfigure(self, *a, **k):
        pass


class Toplevel(Tk):
    def __init__(self, master=None, **kw):
        Misc.__init__(self, master, **kw)


class Widget(Misc):
    pass


class Frame(Widget):
    pass


class LabelFrame(Widget):
    pass


class Label(Widget):
    pass


class Button(Widget):
    def invoke(self):
        cmd = self._opts.get("command")
        return cmd() if cmd else None


class Checkbutton(Button):
    pass


class Radiobutton(Button):
    pass


class Menubutton(Button):
    pass


class Scrollbar(Widget):
    def set(self, *a):
        pass


class Canvas(Widget):
    """Records what was drawn, and lets it be read back through the REAL
    Tk API - find_all / type / coords / itemcget / bbox.

    That is the whole point of the read side. A test that reaches for a
    stub attribute (``canvas._items``) passes here and proves nothing
    about the toolkit; one written against find_all() runs unchanged on
    both, so the same assertions can be checked against real Tk on a
    machine that has a display.

    Sizes are settable (``set_size``) because the geometry under test is
    a function of them and a real widget only gets a size once mapped.
    """

    def __init__(self, master=None, **kw):
        Widget.__init__(self, master, **kw)
        self._items = []
        # What a real Canvas reports before it is mapped. Deliberately
        # useless: a test that forgets set_size() then fails HERE, the
        # way it would on a machine with a display, instead of drawing
        # against a convenient default and failing only there.
        self._size = (1, 1)
        self._opts.setdefault("highlightthickness", 0)
        self._opts.setdefault("borderwidth", 0)

    # -- writing
    def create_rectangle(self, *a, **k):
        self._items.append(("rectangle", list(a), dict(k)))
        return len(self._items)

    def create_line(self, *a, **k):
        self._items.append(("line", list(a), dict(k)))
        return len(self._items)

    def create_text(self, *a, **k):
        self._items.append(("text", list(a), dict(k)))
        return len(self._items)

    create_oval = create_polygon = create_rectangle

    def create_window(self, *a, **k):
        self._items.append(("window", list(a), dict(k)))
        return len(self._items)

    def delete(self, *a):
        self._items = []

    # -- reading, with Tk's own names and Tk's own defaults
    #: What Tk reports for an option that was never set. Only the ones
    #: this project reads are listed; anything else comes back "".
    _ITEM_DEFAULTS = {"anchor": "center", "fill": "black", "text": "",
                      "dash": "", "width": "1.0", "outline": "black"}

    def find_all(self):
        return tuple(range(1, len(self._items) + 1))

    def type(self, item):
        return self._items[item - 1][0]

    def coords(self, item, *a):
        if a:
            self._items[item - 1][1] = list(a)
        return [float(v) for v in self._items[item - 1][1]]

    def itemcget(self, item, option):
        opts = self._items[item - 1][2]
        if option in opts:
            v = opts[option]
            return " ".join(str(x) for x in v) if isinstance(v, tuple) \
                else str(v)
        return self._ITEM_DEFAULTS.get(option, "")

    def itemconfigure(self, item, **kw):
        self._items[item - 1][2].update(kw)

    itemconfig = itemconfigure

    def bbox(self, *a):
        """Bounding box of an item, or of everything when given none.

        Text is measured through the font module so that a test can ask
        'did this label fall off the canvas' the same way on either
        toolkit. Not pixel-exact - real Tk reports one past the last
        pixel - which is why callers must not compare it to the arithmetic
        that produced the coordinates.
        """
        if not a:
            boxes = [self.bbox(i) for i in self.find_all()]
            boxes = [b for b in boxes if b]
            if not boxes:
                return None
            return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes))
        item = a[0]
        kind, co, kw = self._items[item - 1]
        if kind != "text":
            xs, ys = co[0::2], co[1::2]
            return (min(xs), min(ys), max(xs), max(ys))
        fnt = sys.modules["tkinter.font"]
        f = kw.get("font")
        f = fnt.nametofont(f) if isinstance(f, str) else (f or fnt.Font())
        w, h = f.measure(str(kw.get("text", ""))), f.metrics("linespace")
        anchor = str(kw.get("anchor", "center"))
        x, y = co[0], co[1]
        x0 = x - w if anchor.endswith("e") else (
            x if anchor.endswith("w") else x - w / 2)
        y0 = y - h if anchor.startswith("s") else (
            y if anchor.startswith("n") else y - h / 2)
        return (int(x0), int(y0), int(x0 + w), int(y0 + h))

    # -- size
    def set_size(self, width, height):
        """What winfo_width/height will report. A real Canvas only gets
        a size when it is mapped, so a headless test has to say."""
        self._size = (width, height)

    def winfo_width(self):
        return self._size[0]

    def winfo_height(self):
        return self._size[1]

    def configure(self, cnf=None, **kw):
        return Widget.configure(self, cnf, **kw)

    def yview(self, *a):
        """Fraction pair, as the real widget returns it. The stub view
        always shows everything, so a scrollable container built on it
        reads as 'nothing to scroll' instead of crashing on None."""
        return (0.0, 1.0)

    xview = yview

    def yview_scroll(self, *a):
        self._scrolled = getattr(self, "_scrolled", 0) + (a[0] if a else 0)

    xview_scroll = yview_scroll

    def itemconfigure(self, *a, **k):
        pass

    itemconfig = itemconfigure


class Entry(Widget):
    def __init__(self, master=None, **kw):
        Widget.__init__(self, master, **kw)
        self._text = ""
        self._alive = True

    def get(self):
        return self._text

    def insert(self, index, s):
        self._text = self._text + str(s) if index in (END, "end") \
            else str(s) + self._text

    def delete(self, first, last=None):
        self._text = ""

    def select_range(self, a, b):
        pass

    def icursor(self, i):
        pass

    def destroy(self):
        self._alive = False
        Widget.destroy(self)

    def place(self, **kw):
        if not self._alive:
            raise TclError("widget destroyed")
        Widget.place(self, **kw)


class Spinbox(Entry):
    def set(self, v):
        self._text = str(v)


class Combobox(Entry):
    """ttk.Combobox: an Entry that also answers set()/current()."""

    def set(self, v):
        self._text = str(v)

    def current(self, i=None):
        return 0


class Text(Widget):
    def __init__(self, master=None, **kw):
        Widget.__init__(self, master, **kw)
        self._text = ""

    def insert(self, index, s, *tags):
        self._text += str(s)

    def delete(self, a, b=None):
        self._text = ""

    def get(self, a="1.0", b=END):
        return self._text

    def see(self, i):
        pass

    def tag_configure(self, *a, **k):
        pass

    tag_add = tag_remove = tag_configure

    def yview(self, *a):
        pass

    xview = yview

    def index(self, i):
        return "1.0"

    def edit_reset(self):
        pass


class Listbox(Widget):
    def __init__(self, master=None, **kw):
        Widget.__init__(self, master, **kw)
        self._items = []
        self._sel = ()

    def insert(self, index, *items):
        self._items.extend(items)

    def delete(self, a, b=None):
        self._items = []

    def get(self, a, b=None):
        return self._items[a] if b is None else self._items[a:]

    def size(self):
        return len(self._items)

    def curselection(self):
        return self._sel

    def selection_set(self, a, b=None):
        self._sel = (a,)

    def see(self, i):
        pass

    def selection_clear(self, *a, **k):
        self._sel = ()

    def yview(self, *a):
        pass

    xview = yview

    def activate(self, i):
        pass

    def itemconfigure(self, *a, **k):
        pass

    def index(self, i):
        return 0

    def nearest(self, y):
        return 0


class PanedWindow(Widget):
    def add(self, child, **kw):
        pass


class Menu(Widget):
    def add_command(self, **kw):
        pass

    add_separator = add_cascade = add_checkbutton = add_command

    def post(self, *a):
        pass

    def tk_popup(self, *a):
        pass

    def grab_release(self):
        pass


class Message(Widget):
    pass


class Scale(Widget):
    pass


# --- ttk ----------------------------------------------------------------


class _Style:
    def __init__(self, master=None):
        pass

    def configure(self, *a, **k):
        pass

    def map(self, *a, **k):
        pass

    def theme_use(self, *a):
        return "default"

    def theme_names(self):
        return ["default"]

    def lookup(self, *a, **k):
        return ""


class Treeview(Widget):
    """Item tree with the subset of the real API the project uses."""

    def __init__(self, master=None, **kw):
        Widget.__init__(self, master, **kw)
        self._parent = {}          # iid -> parent iid
        self._kids = {"": []}      # iid -> [child iids]
        self._item = {}            # iid -> dict(text, values, tags, open)
        self._sel = ()
        self._focus = ""
        self._n = 0
        self._cols = list(kw.get("columns") or ())
        self._headings = {}
        self._colcfg = {}

    # -- structure
    def insert(self, parent, index, iid=None, **kw):
        if iid is None:
            self._n += 1
            iid = "I%03d" % self._n
        if iid in self._item:
            raise TclError("item %s already exists" % iid)
        vals = list(kw.get("values") or ())
        self._item[iid] = {"text": kw.get("text", ""), "values": vals,
                           "tags": tuple(kw.get("tags") or ()),
                           "open": bool(kw.get("open", False)),
                           "image": kw.get("image", "")}
        self._parent[iid] = parent
        self._kids.setdefault(parent, [])
        self._kids.setdefault(iid, [])
        kids = self._kids[parent]
        kids.append(iid) if index in (END, "end") else kids.insert(index, iid)
        return iid

    def delete(self, *iids):
        for iid in iids:
            for k in list(self._kids.get(iid, [])):
                self.delete(k)
            p = self._parent.pop(iid, None)
            if p is not None and iid in self._kids.get(p, []):
                self._kids[p].remove(iid)
            self._kids.pop(iid, None)
            self._item.pop(iid, None)
        self._sel = tuple(i for i in self._sel if i in self._item)

    def get_children(self, item=""):
        return tuple(self._kids.get(item, ()))

    def parent(self, iid):
        return self._parent.get(iid, "")

    def exists(self, iid):
        return iid in self._item

    def index(self, iid):
        return self._kids[self._parent[iid]].index(iid)

    def move(self, iid, parent, index):
        kids = self._kids[self._parent[iid]]
        kids.remove(iid)
        self._parent[iid] = parent
        self._kids.setdefault(parent, [])
        if index in (END, "end"):
            self._kids[parent].append(iid)
        else:
            self._kids[parent].insert(index, iid)

    def detach(self, *iids):
        for iid in iids:
            self._kids[self._parent[iid]].remove(iid)

    def reattach(self, iid, parent, index):
        self.move(iid, parent, index)

    # -- item data
    def item(self, iid, option=None, **kw):
        d = self._item[iid]
        if kw:
            if "values" in kw:
                kw["values"] = list(kw["values"])
            if "tags" in kw:
                kw["tags"] = tuple(kw["tags"] or ())
            d.update(kw)
            return None
        if option:
            return d.get(option.lstrip("-"))
        return dict(d)

    def set(self, iid, column=None, value=None):
        d = self._item[iid]
        if column is None:
            return {c: self._value(iid, c) for c in self._cols}
        i = self._cols.index(column) if column in self._cols else int(column) - 1
        vals = list(d["values"]) + [""] * (len(self._cols) - len(d["values"]))
        if value is None:
            return vals[i]
        vals[i] = value
        d["values"] = vals
        return value

    def _value(self, iid, col):
        vals = self._item[iid]["values"]
        i = self._cols.index(col)
        return vals[i] if i < len(vals) else ""

    def tag_configure(self, *a, **k):
        pass

    tag_bind = tag_configure

    def tag_has(self, tag, iid=None):
        return tag in self._item[iid]["tags"]

    # -- selection / focus
    def selection(self):
        return tuple(self._sel)

    def selection_set(self, *iids):
        flat = []
        for i in iids:
            flat.extend(i if isinstance(i, (list, tuple)) else [i])
        self._sel = tuple(flat)

    def selection_add(self, *iids):
        self._sel = tuple(list(self._sel) + list(iids))

    def selection_remove(self, *iids):
        self._sel = tuple(i for i in self._sel if i not in iids)

    def selection_toggle(self, *iids):
        pass

    def focus(self, iid=None):
        if iid is None:
            return self._focus
        self._focus = iid

    def see(self, iid):
        pass

    def identify_row(self, y):
        return self._focus

    def identify_column(self, x):
        return "#1"

    def identify_region(self, x, y):
        return "cell"

    def identify(self, *a):
        return "cell"

    def bbox(self, iid, column=None):
        return (0, 0, 60, 20)

    def heading(self, col, **kw):
        if kw:
            self._headings[col] = kw
        return self._headings.get(col, {})

    def column(self, col, **kw):
        if kw:
            self._colcfg.setdefault(col, {}).update(kw)
        return self._colcfg.get(col, {})

    def yview(self, *a):
        pass

    xview = yview

    def yview_moveto(self, *a):
        pass

    def state(self, *a):
        return ()


def install_if_missing(quiet=False) -> bool:
    """Install the stub ONLY when the real tkinter cannot be imported.

    Returns True when the stub was installed. Prints a one-line notice
    unless 'quiet': a test that passed against a stand-in has to say so,
    or a green suite would be indistinguishable from a green program.
    """
    try:
        import tkinter                                    # noqa: F401
    except ImportError:
        install()
        if not quiet:
            print("[tkstub] tkinter is not installed on this Python: "
                  "running against the in-memory stub, not the real "
                  "toolkit")
        return True
    return False


def install():
    """Put the stub in sys.modules as tkinter / tkinter.ttk / ...

    Unconditional: prefer :func:`install_if_missing` in tests. Call this
    directly only to drive widget logic deterministically even where a
    real tkinter exists (no window, no display, no timing).
    """
    tk = types.ModuleType("tkinter")
    g = globals()
    for name, obj in list(g.items()):
        if not name.startswith("_") and name not in ("install", "sys", "types"):
            setattr(tk, name, obj)
    tk.Widget = Widget

    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "Checkbutton",
                 "Radiobutton", "Scrollbar", "Treeview", "LabelFrame",
                 "PanedWindow", "Menubutton", "Spinbox", "Scale",
                 "Combobox"):
        setattr(ttk, name, g[name])
    ttk.Combobox = Combobox
    ttk.Notebook = Frame
    ttk.Separator = Frame
    ttk.Progressbar = Frame
    ttk.Style = _Style
    ttk.Sizegrip = Frame
    tk.ttk = ttk

    mb = types.ModuleType("tkinter.messagebox")
    mb.showinfo = mb.showwarning = mb.showerror = lambda *a, **k: None
    mb.askyesno = mb.askokcancel = mb.askretrycancel = lambda *a, **k: True
    mb.askyesnocancel = lambda *a, **k: True
    tk.messagebox = mb

    fd = types.ModuleType("tkinter.filedialog")
    fd.askopenfilename = fd.asksaveasfilename = lambda *a, **k: ""
    fd.askdirectory = lambda *a, **k: ""
    tk.filedialog = fd

    sd = types.ModuleType("tkinter.simpledialog")
    sd.askstring = lambda *a, **k: ""
    sd.askinteger = lambda *a, **k: 0
    sd.Dialog = Toplevel
    tk.simpledialog = sd

    fnt = types.ModuleType("tkinter.font")

    class _Font:
        """A named font with Tk's own bookkeeping.

        The REGISTRY holds option DICTS, not wrappers, exactly as Tcl
        holds the fonts while tkinter holds a separate Python object.
        That separation is the point: a registry of wrappers would keep
        them alive and __del__ would never fire, hiding the mistake it
        exists to expose - a font created and not held is destroyed
        again, silently, because Tk then reads the name as a family and
        falls back to the default.

        Sizes are reconfigurable and metrics/measure follow from them,
        so a test can sweep the font scale and see the labels grow with
        it - which is what the layout code is measured against.
        """

        #: name -> option dict, as Tk's "font names" list.
        REGISTRY = {}
        ASPECT = 0.55                 # character width, in linespaces

        def __init__(self, root=None, font=None, name=None, exists=False,
                     **options):
            self.name = name or ("font%d" % id(self))
            self.delete_font = not exists
            if exists:
                if self.name not in _Font.REGISTRY:
                    raise TclError("named font %s does not already exist"
                                   % self.name)
                self._opts = _Font.REGISTRY[self.name]
                self._opts.update(options)
                return
            self._opts = {"family": "TkDefaultFont", "size": 10,
                          "weight": "normal"}
            self._opts.update(options)
            if name:
                _Font.REGISTRY[self.name] = self._opts

        def __del__(self):
            try:
                if self.delete_font:
                    _Font.REGISTRY.pop(self.name, None)
            except Exception:
                pass

        def measure(self, s):
            return int(round(len(str(s)) * self.metrics() * self.ASPECT))

        def metrics(self, *a):
            return int(round(abs(self._opts["size"]) * 1.7)) or 1

        def actual(self, option=None, *_a):
            """Tk returns ONE value when an option is named, and the
            whole dict only when none is. Returning the dict either way
            let setup_panel.apply_font_scale() blow up on abs() here
            while working on the real toolkit - a stub that hides the
            code it is standing in for is worse than no stub."""
            if option is None:
                return dict(self._opts)
            return self._opts.get(str(option).lstrip("-"))

        def cget(self, k):
            return self._opts.get(k)

        def configure(self, **k):
            self._opts.update(k)

        config = configure

    def _nametofont(name):
        return _Font(name=name, exists=True)

    for _n, _sz in (("TkDefaultFont", 10), ("TkTextFont", 10),
                    ("TkFixedFont", 10), ("TkMenuFont", 10),
                    ("TkHeadingFont", 10), ("TkCaptionFont", 10),
                    ("TkSmallCaptionFont", 9), ("TkIconFont", 10),
                    ("TkTooltipFont", 9)):
        _Font.REGISTRY[_n] = {"family": "TkDefaultFont", "size": _sz,
                              "weight": "normal"}

    fnt.Font = _Font
    fnt.nametofont = _nametofont
    fnt.names = lambda *a: sorted(_Font.REGISTRY)
    fnt.families = lambda *a: ["TkDefaultFont"]
    tk.font = fnt

    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.messagebox"] = mb
    sys.modules["tkinter.filedialog"] = fd
    sys.modules["tkinter.simpledialog"] = sd
    sys.modules["tkinter.font"] = fnt
    return tk

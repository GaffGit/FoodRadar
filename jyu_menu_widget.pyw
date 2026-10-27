"""JYU student restaurant menu desktop widget.

A borderless window that sits below all other windows and shows today's
lunch menus of the University of Jyväskylä student restaurants (Semma).
Right-click the widget or press the gear icon to open settings.
"""

import ctypes
import datetime as dt
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import urllib.request
import webbrowser
import winreg

APP_ID = "JYUMenuWidget"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_ID)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CACHE_PATH = os.path.join(CONFIG_DIR, "cache.json")
API_URL = "https://{}/menuapi/feed/json?costNumber={}&language={}"
SEMMA, COMPASS = "www.semma.fi", "www.compass-group.fi"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# Cost numbers of the JYU campus restaurants (Semma unless listed in HOSTS).
RESTAURANTS = {
    "1401": "Lozzi",
    "0301": "Taide",
    "1419": "Ilokivi",
    "1413": "Tilia",
    "1405": "Syke",
    "1404": "Belvedere",
    "1408": "Piato",
    "1414": "Uno",
    "1403": "Ylistö",
    "1416": "Rentukka",
    "1411": "Normaalikoulu",
}
# Taide (Lähde library) is run by Compass Group, which serves the same feed format.
HOSTS = {"0301": COMPASS}
# The feed's own names that are too long for the widget.
DISPLAY_NAMES = {"0301": "Ravintola Taide"}
# Semma's feed leaves the prices empty, so show its price list from 1.1.2026 instead
# (semma.fi/ajankohtaista/semman-ravintoloiden-hinnat-paivittyvat-1.1.2026).
# Normaalikoulu is a school restaurant and not on that list.
PRICE_GROUPS = {
    "fi": ["Opiskelija", "Jatko-opiskelija", "Henkilökunta", "Ulkopuolinen"],
    "en": ["Student", "Postgraduate", "Staff", "Visitor"],
}
SEMMA_PRICES = {cost: ("3,10 €", "6,30 €", "6,70 €", "9,00 €")
                for cost in RESTAURANTS if cost not in HOSTS and cost != "1411"}
SEMMA_PRICES.update({cost: ("3,10 €", "6,30 €", "6,95 €", "9,00 €") for cost in ("1416", "1419")})

DEFAULT_CONFIG = {
    "restaurants": ["1401", "1419", "1408", "1403"],
    "custom": {},
    "language": "fi",
    "opacity": 92,
    "font_size": 10,
    "hide_empty": True,
    "refresh_minutes": 60,
    "x": None,
    "y": None,
    "width": None,
    "height": None,
}

TEXTS = {
    "fi": {
        "days": ["maanantai", "tiistai", "keskiviikko", "torstai", "perjantai", "lauantai", "sunnuntai"],
        "no_menu": "Ei ruokalistaa",
        "nothing": "Valituissa ravintoloissa ei ole ruokalistaa tälle päivälle.",
        "no_selection": "Valitse ravintolat asetuksista (⚙).",
        "loading": "Ladataan…",
        "updated": "Päivitetty {}",
        "offline": "Ei yhteyttä – näytetään tallennettu lista",
        "refresh": "Päivitä",
        "today": "Tänään",
        "settings": "Asetukset",
        "exit": "Sulje",
    },
    "en": {
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "no_menu": "No menu",
        "nothing": "The selected restaurants have no menu for this day.",
        "no_selection": "Choose restaurants in settings (⚙).",
        "loading": "Loading…",
        "updated": "Updated {}",
        "offline": "Offline – showing saved menu",
        "refresh": "Refresh",
        "today": "Today",
        "settings": "Settings",
        "exit": "Exit",
    },
}

COLORS = {
    "bg": "#1d1f24",
    "header": "#262930",
    "fg": "#e9e9ec",
    "dim": "#9a9ea8",
    "faint": "#6d727d",
    "accent": "#8cc8ff",
    "hover": "#3a3e48",
}

user32 = ctypes.windll.user32
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x00000080, 0x00040000


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def fetch_menu(cost, lang):
    # Unknown (custom) numbers are tried at Semma first, then Compass Group.
    hosts = [HOSTS[cost]] if cost in HOSTS else [SEMMA, COMPASS]
    for host in hosts:
        req = urllib.request.Request(API_URL.format(host, cost, lang), headers={"User-Agent": APP_ID})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("RestaurantName"):
            HOSTS[cost] = host
            return data
    raise ValueError(f"unknown restaurant {cost}")


def default_price(cost, lang):
    prices = SEMMA_PRICES.get(cost)
    return " / ".join(f"{group} {price}" for group, price in zip(PRICE_GROUPS[lang], prices)) if prices else ""


def split_diets(component):
    """'Meatballs (*, A, L, M)' -> ('Meatballs', '*, A, L, M')"""
    text = " ".join(component.split())
    match = re.match(r"^(.*?)\s*\(([^()]*)\)$", text)
    if match and match.group(1):
        return match.group(1), match.group(2)
    return text, ""


def autostart_command():
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def get_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_ID)
            return True
    except OSError:
        return False


def set_autostart(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_ID)
            except OSError:
                pass


class MenuWidget:
    def __init__(self):
        self.config = {**DEFAULT_CONFIG, **load_json(CONFIG_PATH, {})}
        cache = load_json(CACHE_PATH, {})
        self.menus = cache.get("menus", {}) if cache.get("language") == self.config["language"] else {}
        self.fetched_at = cache.get("fetched_at")
        self.offline = False
        self.loading = False
        self.refresh_again = False
        self.day_offset = 0
        self.today = dt.date.today()
        self.results = queue.Queue()
        self.settings_win = None

        self.root = tk.Tk()
        self.root.title("JYU Menu")
        self.root.overrideredirect(True)
        self.root.configure(bg=COLORS["bg"])
        self.scale = self.root.winfo_fpixels("1i") / 96

        size = self.config["font_size"]
        self.fonts = {
            "title": tkfont.Font(family="Segoe UI Semibold", size=size + 1),
            "rest": tkfont.Font(family="Segoe UI Semibold", size=size + 1),
            "cat": tkfont.Font(family="Segoe UI", size=size - 2),
            "food": tkfont.Font(family="Segoe UI", size=size),
            "small": tkfont.Font(family="Segoe UI", size=size - 2),
            "icon": tkfont.Font(family="Segoe UI Symbol", size=size + 1),
        }

        self.build_ui()
        self.place_window()
        self.apply_opacity()
        self.root.update_idletasks()
        self.make_tool_window()
        self.render()
        self.refresh()

        self.root.after(200, self.poll_results)
        self.root.after(500, self.keep_at_bottom)
        self.root.after(60_000, self.tick)

    # ----- window ---------------------------------------------------------

    def t(self, key):
        return TEXTS[self.config["language"]][key]

    def hwnd(self):
        return int(self.root.wm_frame(), 16)

    def make_tool_window(self):
        """Hide the widget from the taskbar and Alt+Tab."""
        hwnd = self.hwnd()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)

    def keep_at_bottom(self):
        user32.SetWindowPos(self.hwnd(), HWND_BOTTOM, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        self.root.after(500, self.keep_at_bottom)

    def place_window(self):
        width = self.config["width"] or int(340 * self.scale)
        height = self.config["height"] or int(520 * self.scale)
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        x, y = self.config["x"], self.config["y"]
        if x is None or y is None or not (vx <= x < vx + vw - 40 and vy <= y < vy + vh - 40):
            x = self.root.winfo_screenwidth() - width - int(24 * self.scale)
            y = int(24 * self.scale)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def apply_opacity(self):
        self.root.attributes("-alpha", max(30, min(100, self.config["opacity"])) / 100)

    def save_geometry(self):
        self.config.update(
            x=self.root.winfo_x(), y=self.root.winfo_y(),
            width=self.root.winfo_width(), height=self.root.winfo_height(),
        )
        save_json(CONFIG_PATH, self.config)

    # ----- UI -------------------------------------------------------------

    def icon_button(self, parent, text, command):
        label = tk.Label(parent, text=text, font=self.fonts["icon"], bg=COLORS["header"],
                         fg=COLORS["dim"], padx=6, cursor="hand2")
        label.bind("<Button-1>", lambda e: command())
        label.bind("<Enter>", lambda e: label.config(fg=COLORS["fg"], bg=COLORS["hover"]))
        label.bind("<Leave>", lambda e: label.config(fg=COLORS["dim"], bg=COLORS["header"]))
        return label

    def build_ui(self):
        header = tk.Frame(self.root, bg=COLORS["header"], pady=6)
        header.pack(fill="x")
        self.icon_button(header, "◀", lambda: self.change_day(-1)).pack(side="left", padx=(6, 0))
        self.title = tk.Label(header, font=self.fonts["title"], bg=COLORS["header"], fg=COLORS["fg"])
        self.title.pack(side="left", fill="x", expand=True)
        self.title.bind("<Double-Button-1>", lambda e: self.go_today())
        self.icon_button(header, "▶", lambda: self.change_day(1)).pack(side="left")
        self.icon_button(header, "⟳", self.refresh).pack(side="left")
        self.icon_button(header, "⚙", self.open_settings).pack(side="left", padx=(0, 6))
        for widget in (header, self.title):
            widget.bind("<ButtonPress-1>", self.start_move)
            widget.bind("<B1-Motion>", self.do_move)
            widget.bind("<ButtonRelease-1>", lambda e: self.save_geometry())

        footer = tk.Frame(self.root, bg=COLORS["bg"])
        footer.pack(fill="x", side="bottom")
        self.status = tk.Label(footer, font=self.fonts["small"], bg=COLORS["bg"], fg=COLORS["faint"],
                               anchor="w", padx=12, pady=3)
        self.status.pack(side="left", fill="x", expand=True)
        grip = tk.Label(footer, text="◢", font=self.fonts["small"], bg=COLORS["bg"], fg=COLORS["faint"],
                        cursor="size_nw_se", padx=4)
        grip.pack(side="right")
        grip.bind("<ButtonPress-1>", self.start_resize)
        grip.bind("<B1-Motion>", self.do_resize)
        grip.bind("<ButtonRelease-1>", lambda e: self.save_geometry())

        self.text = tk.Text(self.root, bg=COLORS["bg"], fg=COLORS["fg"], bd=0, highlightthickness=0,
                            wrap="word", padx=14, pady=8, cursor="arrow", font=self.fonts["food"],
                            spacing1=1, spacing3=1, takefocus=0)
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("rest", font=self.fonts["rest"], foreground=COLORS["accent"], spacing1=10)
        self.text.tag_configure("time", font=self.fonts["small"], foreground=COLORS["faint"])
        self.text.tag_configure("cat", font=self.fonts["cat"], foreground=COLORS["dim"], spacing1=5)
        self.text.tag_configure("food", lmargin1=8, lmargin2=8)
        self.text.tag_configure("diet", font=self.fonts["small"], foreground=COLORS["faint"])
        self.text.tag_configure("note", foreground=COLORS["dim"])

        self.menu = tk.Menu(self.root, tearoff=0)
        for widget in (self.root, header, self.title, self.text, footer, self.status):
            widget.bind("<Button-3>", self.show_menu)

    def show_menu(self, event):
        self.menu.delete(0, "end")
        self.menu.add_command(label=self.t("today"), command=self.go_today)
        self.menu.add_command(label=self.t("refresh"), command=self.refresh)
        self.menu.add_command(label=self.t("settings"), command=self.open_settings)
        self.menu.add_separator()
        self.menu.add_command(label=self.t("exit"), command=self.root.destroy)
        self.menu.tk_popup(event.x_root, event.y_root)

    def start_move(self, event):
        self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def do_move(self, event):
        self.root.geometry(f"+{event.x_root - self.drag[0]}+{event.y_root - self.drag[1]}")

    def start_resize(self, event):
        self.drag = (event.x_root, event.y_root, self.root.winfo_width(), self.root.winfo_height())

    def do_resize(self, event):
        x0, y0, w0, h0 = self.drag
        minimum = int(200 * self.scale)
        w = max(minimum, w0 + event.x_root - x0)
        h = max(minimum, h0 + event.y_root - y0)
        self.root.geometry(f"{w}x{h}")

    # ----- data -----------------------------------------------------------

    def selected(self):
        names = {**RESTAURANTS, **self.config["custom"]}
        return [(cost, names.get(cost, cost)) for cost in self.config["restaurants"] if cost in names]

    def refresh(self):
        if self.loading:
            self.refresh_again = True  # settings changed mid-fetch; fetch again afterwards
            return
        self.loading = True
        self.refresh_again = False
        self.render_status()
        costs = [cost for cost, _ in self.selected()]
        lang = self.config["language"]
        threading.Thread(target=self.fetch_all, args=(costs, lang), daemon=True).start()

    def fetch_all(self, costs, lang):
        menus, failed = {}, False
        for cost in costs:
            try:
                menus[cost] = fetch_menu(cost, lang)
            except Exception:
                failed = True
        self.results.put((lang, menus, failed))

    def poll_results(self):
        try:
            while True:
                lang, menus, failed = self.results.get_nowait()
                self.loading = False
                if lang != self.config["language"]:
                    self.menus = {}
                    self.refresh()
                    continue
                self.menus.update(menus)
                self.offline = failed
                if menus:
                    self.fetched_at = dt.datetime.now().isoformat(timespec="minutes")
                    save_json(CACHE_PATH, {"language": lang, "fetched_at": self.fetched_at, "menus": self.menus})
                self.render()
                if self.refresh_again:
                    self.refresh()
        except queue.Empty:
            pass
        self.root.after(200, self.poll_results)

    def tick(self):
        if dt.date.today() != self.today:
            self.today = dt.date.today()
            self.day_offset = 0
            self.refresh()
        elif self.fetched_at:
            age = dt.datetime.now() - dt.datetime.fromisoformat(self.fetched_at)
            if age > dt.timedelta(minutes=self.config["refresh_minutes"]):
                self.refresh()
        self.root.after(60_000, self.tick)

    # ----- rendering ------------------------------------------------------

    def change_day(self, step):
        self.day_offset = max(-7, min(7, self.day_offset + step))
        self.render()

    def go_today(self):
        self.day_offset = 0
        self.render()

    def render_status(self):
        if self.loading:
            text = self.t("loading")
        elif self.offline:
            text = self.t("offline")
        elif self.fetched_at:
            text = self.t("updated").format(dt.datetime.fromisoformat(self.fetched_at).strftime("%H:%M"))
        else:
            text = ""
        self.status.config(text=text)

    def render(self):
        day = self.today + dt.timedelta(days=self.day_offset)
        name = self.t("days")[day.weekday()]
        prefix = f"{self.t('today')} · " if self.day_offset == 0 else ""
        self.title.config(text=f"{prefix}{name.capitalize()} {day.day}.{day.month}.")
        self.render_status()

        text = self.text
        text.config(state="normal")
        text.delete("1.0", "end")
        selected = self.selected()
        shown = 0
        for cost, fallback in selected:
            data = self.menus.get(cost)
            if not data:
                continue
            entry = next((d for d in data.get("MenusForDays") or [] if d["Date"][:10] == day.isoformat()), None)
            set_menus = [m for m in (entry or {}).get("SetMenus") or [] if m.get("Components")]
            if not set_menus and self.config["hide_empty"]:
                continue

            link = f"link{cost}"
            name = DISPLAY_NAMES.get(cost) or data.get("RestaurantName") or fallback
            text.insert("end", ("\n" if shown else "") + name, ("rest", link))
            url = data.get("RestaurantUrl")
            if url:
                text.tag_bind(link, "<Button-1>", lambda e, u=url: webbrowser.open(u))
                text.tag_bind(link, "<Enter>", lambda e: text.config(cursor="hand2"))
                text.tag_bind(link, "<Leave>", lambda e: text.config(cursor="arrow"))
            if entry and entry.get("LunchTime"):
                text.insert("end", "  " + entry["LunchTime"], "time")
            text.insert("end", "\n")
            shown += 1

            if not set_menus:
                text.insert("end", self.t("no_menu") + "\n", "note")
            last_price = None
            fallback_price = default_price(cost, self.config["language"])
            for menu in sorted(set_menus, key=lambda m: m.get("SortOrder") or 0):
                category = (menu.get("Name") or "").strip()
                if category:
                    text.insert("end", category.upper() + "\n", "cat")
                # Prices are usually the same for every dish, so only show changes.
                price = " ".join((menu.get("Price") or "").split()) or fallback_price
                if price and price != last_price:
                    text.insert("end", price + "\n", ("food", "diet"))
                    last_price = price
                for component in menu["Components"]:
                    food, diets = split_diets(component)
                    text.insert("end", food, "food")
                    if diets:
                        text.insert("end", f"  {diets}", ("food", "diet"))
                    text.insert("end", "\n", "food")

        if not selected:
            text.insert("end", self.t("no_selection"), "note")
        elif not shown and not self.loading:
            text.insert("end", self.t("nothing"), "note")
        text.config(state="disabled")

    # ----- settings -------------------------------------------------------

    def open_settings(self):
        if self.settings_win and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus_force()
            return
        self.settings_win = SettingsWindow(self)

    def apply_settings(self, new_config, autostart):
        old = self.config
        self.config = new_config
        save_json(CONFIG_PATH, self.config)
        try:
            set_autostart(autostart)
        except OSError:
            pass

        size = self.config["font_size"]
        for key, font in self.fonts.items():
            font.configure(size=size + {"title": 1, "rest": 1, "icon": 1, "cat": -2, "small": -2}.get(key, 0))
        self.apply_opacity()

        if old["language"] != self.config["language"]:
            self.menus = {}
        missing = [cost for cost in self.config["restaurants"] if cost not in self.menus]
        self.render()
        if missing or old["language"] != self.config["language"]:
            self.refresh()


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        cfg = app.config
        self.custom = dict(cfg["custom"])
        self.checks = {}

        win = self.win = tk.Toplevel(app.root)
        win.title("JYU Menu – " + app.t("settings"))
        win.resizable(False, False)
        win.attributes("-topmost", True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        pad = {"padx": 14, "pady": (10, 2)}

        fi = cfg["language"] == "fi"
        tk.Label(win, text="Ravintolat" if fi else "Restaurants", font=app.fonts["rest"]).pack(anchor="w", **pad)
        self.list_frame = tk.Frame(win)
        self.list_frame.pack(fill="x", padx=14)
        self.selected = list(cfg["restaurants"])
        # Display order: shown restaurants in their current order, then the rest.
        self.order = self.selected + [c for c in {**RESTAURANTS, **self.custom} if c not in self.selected]
        self.build_list()

        add = tk.Frame(win)
        add.pack(fill="x", padx=14, pady=(6, 0))
        tk.Label(add, text="Lisää numerolla:" if fi else "Add by number:").pack(side="left")
        self.cost_entry = tk.Entry(add, width=8)
        self.cost_entry.pack(side="left", padx=6)
        tk.Button(add, text="Lisää" if fi else "Add", command=self.add_custom).pack(side="left")
        self.add_status = tk.Label(win, fg="#a33", text="")
        self.add_status.pack(anchor="w", padx=14)

        tk.Label(win, text="Näkymä" if fi else "Display", font=app.fonts["rest"]).pack(anchor="w", **pad)
        self.language = tk.StringVar(value=cfg["language"])
        lang_row = tk.Frame(win)
        lang_row.pack(anchor="w", padx=14)
        tk.Label(lang_row, text="Kieli:" if fi else "Language:").pack(side="left")
        tk.Radiobutton(lang_row, text="Suomi", variable=self.language, value="fi").pack(side="left")
        tk.Radiobutton(lang_row, text="English", variable=self.language, value="en").pack(side="left")

        self.opacity = tk.IntVar(value=cfg["opacity"])
        row = tk.Frame(win)
        row.pack(anchor="w", padx=14)
        tk.Label(row, text="Läpinäkymättömyys %:" if fi else "Opacity %:").pack(side="left")
        tk.Scale(row, from_=30, to=100, orient="horizontal", variable=self.opacity, length=160,
                 command=lambda v: app.root.attributes("-alpha", int(v) / 100)).pack(side="left")

        self.font_size = tk.IntVar(value=cfg["font_size"])
        row = tk.Frame(win)
        row.pack(anchor="w", padx=14)
        tk.Label(row, text="Fonttikoko:" if fi else "Font size:").pack(side="left")
        tk.Spinbox(row, from_=8, to=16, textvariable=self.font_size, width=4).pack(side="left", padx=6)

        self.hide_empty = tk.BooleanVar(value=cfg["hide_empty"])
        tk.Checkbutton(win, variable=self.hide_empty,
                       text="Piilota ravintolat, joilla ei ole listaa" if fi else "Hide restaurants without a menu"
                       ).pack(anchor="w", padx=14)
        self.autostart = tk.BooleanVar(value=get_autostart())
        tk.Checkbutton(win, variable=self.autostart,
                       text="Käynnistä Windowsin mukana" if fi else "Start with Windows").pack(anchor="w", padx=14)

        buttons = tk.Frame(win)
        buttons.pack(fill="x", padx=14, pady=12)
        tk.Button(buttons, text="Peruuta" if fi else "Cancel", width=10, command=self.cancel).pack(side="right")
        tk.Button(buttons, text="Tallenna" if fi else "Save", width=10, command=self.save).pack(side="right", padx=6)

        win.update_idletasks()
        x = app.root.winfo_x() - win.winfo_width() - 12
        win.geometry(f"+{max(0, x)}+{app.root.winfo_y()}")
        win.focus_force()

    def build_list(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.checks = {}
        names = {**RESTAURANTS, **self.custom}
        for index, cost in enumerate(self.order):
            row = tk.Frame(self.list_frame)
            row.pack(fill="x")
            for arrow, step, enabled in (("▲", -1, index > 0), ("▼", 1, index < len(self.order) - 1)):
                button = tk.Label(row, text=arrow, fg="#333" if enabled else "#ccc",
                                  cursor="hand2" if enabled else "", padx=2)
                button.pack(side="left")
                if enabled:
                    button.bind("<Button-1>", lambda e, i=index, s=step: self.move(i, s))
            var = tk.BooleanVar(value=cost in self.selected)
            var.trace_add("write", lambda *_, c=cost, v=var: self.toggle(c, v.get()))
            tk.Checkbutton(row, text=names[cost], variable=var).pack(side="left")
            if cost in self.custom:
                tk.Label(row, text=f"({cost})", fg="#888").pack(side="left")
                remove = tk.Label(row, text="✕", fg="#a33", cursor="hand2")
                remove.pack(side="right")
                remove.bind("<Button-1>", lambda e, c=cost: self.remove_custom(c))
            self.checks[cost] = var

    def move(self, index, step):
        order = self.order
        order[index], order[index + step] = order[index + step], order[index]
        self.build_list()

    def toggle(self, cost, checked):
        if checked and cost not in self.selected:
            self.selected.append(cost)
        elif not checked and cost in self.selected:
            self.selected.remove(cost)

    def add_custom(self):
        cost = self.cost_entry.get().strip()
        if not cost.isdigit() or cost in RESTAURANTS or cost in self.custom:
            self.add_status.config(text="?")
            return
        self.win.config(cursor="watch")
        self.win.update()
        try:
            data = fetch_menu(cost, self.language.get())
        except Exception:
            fi = self.app.config["language"] == "fi"
            self.add_status.config(text="Ravintolaa ei löytynyt" if fi else "Restaurant not found")
            return
        finally:
            self.win.config(cursor="")
        self.add_status.config(text="")
        self.custom[cost] = data["RestaurantName"]
        self.selected.append(cost)
        self.order.append(cost)
        self.cost_entry.delete(0, "end")
        self.build_list()

    def remove_custom(self, cost):
        self.custom.pop(cost, None)
        self.order.remove(cost)
        if cost in self.selected:
            self.selected.remove(cost)
        self.build_list()

    def cancel(self):
        self.app.apply_opacity()
        self.win.destroy()

    def save(self):
        try:
            font_size = max(8, min(16, int(self.font_size.get())))
        except (tk.TclError, ValueError):
            font_size = self.app.config["font_size"]
        new_config = {
            **self.app.config,
            "restaurants": [cost for cost in self.order if cost in self.selected],
            "custom": self.custom,
            "language": self.language.get(),
            "opacity": self.opacity.get(),
            "font_size": font_size,
            "hide_empty": self.hide_empty.get(),
        }
        self.app.apply_settings(new_config, self.autostart.get())
        self.win.destroy()


def main():
    # Only one widget at a time (e.g. autostart + manual launch).
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, f"Local\\{APP_ID}")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    MenuWidget().root.mainloop()


if __name__ == "__main__":
    main()

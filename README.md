# JYU Menu Widget

Desktop widget that stays below all other windows and shows the day's lunch menus of the
University of Jyväskylä student restaurants (Semma).

## Run

Double-click `jyu_menu_widget.pyw`, or:

```
pythonw jyu_menu_widget.pyw
```

Needs only Python 3 on Windows (standard library, no installs).

## Use

- **◀ ▶** browse days, double-click the date to jump back to today
- **⟳** refresh, **⚙** settings (also on right-click, together with *Exit*)
- Drag the header to move, drag **◢** in the bottom-right corner to resize
- Click a restaurant name to open its page on semma.fi

Settings: restaurants to show, language (fi/en), opacity, font size, hiding restaurants
without a menu, and *Start with Windows*. Other Semma restaurants can be added by their
cost number (`costNumber` in the menu feed URL below).

## Data sources

The menus, opening times and prices shown in the widget are not our own. They are fetched
from the restaurant operators' public menu feeds:

- **[Semma](https://www.semma.fi/)** – Lozzi, Ilokivi, Tilia, Syke, Belvedere, Piato, Uno, Ylistö,
  Rentukka and Normaalikoulu:
  `https://www.semma.fi/menuapi/feed/json?costNumber=<n>&language=fi|en`
- **[Compass Group](https://www.compass-group.fi/)** – Ravintola Taide (`0301`): the same path on
  `www.compass-group.fi`

The menus belong to these providers, and they decide what is in them. For allergies, diets and up-to-da
te
information, check the restaurant's own page (click its name in the widget) or ask the staff.
This project is not affiliated with Semma, Compass Group or the University of Jyväskylä.


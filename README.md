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

Settings and the last fetched menus are stored in `%APPDATA%\JYUMenuWidget`.
Data comes from `https://www.semma.fi/menuapi/feed/json?costNumber=<n>&language=fi|en`, and for
Compass Group restaurants such as Taide (`0301`) from the same path on `www.compass-group.fi`.

## Prices

Taide's prices come from the Compass Group feed. Semma's feed leaves prices empty, so the widget
shows Semma's price list from 1.1.2026 instead (`SEMMA_PRICES` in `jyu_menu_widget.pyw`):

| | Opiskelija | Jatko-opiskelija | Henkilökunta | Ulkopuolinen |
|---|---|---|---|---|
| Semma restaurants | 3,10 € | 6,30 € | 6,70 € | 9,00 € |
| Rentukka, Ilokivi | 3,10 € | 6,30 € | 6,95 € | 9,00 € |

These are hardcoded, so update them when Semma changes its prices. Normaalikoulu and restaurants
added by number show no price unless their feed has one.

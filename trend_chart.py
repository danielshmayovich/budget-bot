"""Generate a trend PNG for the /trend Telegram command.

Two panels:
  TOP  — Monthly totals bar chart (actual vs budget), colored by budget status
  BOTTOM — Top-8 YTD categories horizontal bars with budget markers
"""

import io
from collections import defaultdict

try:
    from bidi.algorithm import get_display as _bidi_display
    import logging as _log; _log.info("trend_chart: python-bidi loaded")
    def _h(text: str) -> str:
        return _bidi_display(text, base_dir='R')
except ImportError:
    import logging as _log; _log.warning("trend_chart: python-bidi missing, using pure-Python fallback")
    import re as _re
    def _h(text: str) -> str:
        # Pure-Python visual-order converter for matplotlib LTR renderer.
        # Splits into Hebrew runs (U+0590-U+05FF) and non-Hebrew segments,
        # reverses each Hebrew run, then reverses segment order to model RTL.
        parts = _re.split(r'([֐-׿]+)', text)
        result = [p[::-1] if p and '֐' <= p[0] <= '׿' else p
                  for p in parts]
        return ''.join(reversed(result))

import matplotlib
matplotlib.use("Agg")  # non-interactive, no display required
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np

# ── Status palette ────────────────────────────────────────────────────────────
# green  = under budget (≤ 75%)   #22c55e
# amber  = near budget (75–100%)  #f59e0b
# red    = over budget (> 100%)   #ef4444
# budget = planned line/bar       #94a3b8
# income = income reference       #60a5fa
CLR_GREEN  = "#22c55e"
CLR_AMBER  = "#f59e0b"
CLR_RED    = "#ef4444"
CLR_BUDGET = "#94a3b8"
CLR_BG     = "#ffffff"
CLR_SURFACE= "#f1f5f9"
CLR_TEXT   = "#1e293b"
CLR_MUTED  = "#64748b"
CLR_GRID   = "#e2e8f0"


def _status_color(actual, budget):
    if budget <= 0:
        return CLR_GREEN
    pct = actual / budget
    if pct > 1.0:
        return CLR_RED
    if pct >= 0.75:
        return CLR_AMBER
    return CLR_GREEN


def _fmt(n):
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(int(n))


def generate(monthly_data: list) -> bytes:
    """Return PNG bytes for the trend chart.

    monthly_data: list of dicts from excel_handler.get_monthly_summary()
      each: {month_num, month_name, total_exp, total_budget, categories: [...]}
    """
    if not monthly_data:
        return _empty_chart()

    # ── Aggregate YTD category data ──────────────────────────────────────────
    ytd: dict = defaultdict(lambda: {"actual": 0.0, "budget": 0.0})
    for m in monthly_data:
        for c in m.get("categories", []):
            ytd[c["name"]]["actual"] += c["actual"]
            ytd[c["name"]]["budget"] += c.get("budget", 0)

    top_cats = sorted(ytd.items(), key=lambda x: -x[1]["actual"])[:8]

    # ── Layout ───────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(10, 9), dpi=130, facecolor=CLR_BG)
    gs  = fig.add_gridspec(
        2, 1,
        height_ratios=[1, 1.4],
        hspace=0.55,
        left=0.08, right=0.97,
        top=0.92, bottom=0.06,
    )
    ax_monthly = fig.add_subplot(gs[0])
    ax_cats    = fig.add_subplot(gs[1])

    fig.suptitle(_h("דוח מגמה — תקציב משפחתי"), fontsize=13, fontweight="bold",
                 color=CLR_TEXT, x=0.97, ha="right")

    _draw_monthly(ax_monthly, monthly_data)
    _draw_categories(ax_cats, top_cats)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor=CLR_BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _style_axes(ax, title, xlabel=None):
    ax.set_facecolor(CLR_SURFACE)
    ax.set_title(title, fontsize=10, fontweight="bold", color=CLR_TEXT,
                 loc="right", pad=6)
    ax.tick_params(colors=CLR_MUTED, labelsize=8)
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.yaxis.set_tick_params(length=0)
    ax.xaxis.set_tick_params(length=0)
    for gline in ax.yaxis.get_gridlines():
        gline.set_color(CLR_GRID)
        gline.set_linewidth(0.6)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, color=CLR_GRID, linewidth=0.6)
    ax.xaxis.grid(False)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=8, color=CLR_MUTED)


def _draw_monthly(ax, monthly_data):
    months     = [m["month_name"] for m in monthly_data]
    totals     = [m["total_exp"]  for m in monthly_data]
    budgets    = [m["total_budget"] for m in monthly_data]
    colors     = [_status_color(e, b) for e, b in zip(totals, budgets)]
    x          = np.arange(len(months))
    bar_w      = 0.55

    bars = ax.bar(x, totals, width=bar_w, color=colors, zorder=3,
                  linewidth=0, edgecolor=CLR_BG)

    # Budget line (only where budget > 0)
    for i, (xi, bud) in enumerate(zip(x, budgets)):
        if bud > 0:
            ax.plot([xi - bar_w / 2, xi + bar_w / 2], [bud, bud],
                    color=CLR_BUDGET, linewidth=1.5, zorder=4)

    # Direct labels on bars (skip if bar is very short)
    max_val = max(totals) if totals else 1
    for bar, val in zip(bars, totals):
        if val > max_val * 0.05:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max_val * 0.015,
                _fmt(val),
                ha="center", va="bottom", fontsize=7, color=CLR_TEXT,
                fontweight="bold",
            )

    ax.set_xticks(x)
    ax.set_xticklabels([_h(m) for m in months], fontsize=8, color=CLR_MUTED)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: _fmt(v)))
    ax.set_xlim(-0.6, len(months) - 0.4)
    ax.set_ylim(0, max(totals + [1]) * 1.18)

    _style_axes(ax, _h("הוצאות חודשיות (₪)"))

    # Legend
    patches = [
        mpatches.Patch(color=CLR_GREEN,  label=_h("בתוך תקציב")),
        mpatches.Patch(color=CLR_AMBER,  label=_h("קרוב לגבול (75%+)")),
        mpatches.Patch(color=CLR_RED,    label=_h("חריגה")),
        mpatches.Patch(color=CLR_BUDGET, label=_h("יעד תקציב")),
    ]
    ax.legend(handles=patches, fontsize=7, loc="upper left",
              framealpha=0, labelcolor=CLR_MUTED, handlelength=1.2)


def _draw_categories(ax, top_cats):
    if not top_cats:
        ax.text(0.5, 0.5, _h("אין נתוני קטגוריה"), ha="center", va="center",
                color=CLR_MUTED, transform=ax.transAxes)
        _style_axes(ax, _h("קטגוריות מובילות — YTD"))
        return

    names   = [_h(n[:22]) for n, _ in reversed(top_cats)]
    actuals = [v["actual"]  for _, v in reversed(top_cats)]
    budgets = [v["budget"]  for _, v in reversed(top_cats)]
    colors  = [_status_color(a, b) for a, b in zip(actuals, budgets)]
    y       = np.arange(len(names))
    bar_h   = 0.55

    # Actual bars
    ax.barh(y, actuals, height=bar_h, color=colors, zorder=3,
            linewidth=0, edgecolor=CLR_BG)

    # Budget markers (vertical tick)
    for yi, bud in zip(y, budgets):
        if bud > 0:
            ax.plot([bud, bud], [yi - bar_h / 2, yi + bar_h / 2],
                    color=CLR_BUDGET, linewidth=2, zorder=4, solid_capstyle="butt")

    # Direct labels
    max_val = max(actuals) if actuals else 1
    for yi, (actual, budget) in enumerate(zip(actuals, budgets)):
        label = _fmt(actual)
        if budget > 0:
            pct = int(actual / budget * 100)
            label += f"  ({pct}%)"
        ax.text(actual + max_val * 0.01, yi, label,
                va="center", ha="left", fontsize=7.5,
                color=CLR_TEXT, fontweight="bold")

    # Draw category labels manually to avoid matplotlib RTL axis detection
    ax.set_yticks([])
    for yi, name in zip(y, names):
        ax.text(-max_val * 0.01, yi, name, va="center", ha="right",
                fontsize=8.5, color=CLR_TEXT)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: _fmt(v) if v >= 0 else ""))
    ax.set_xlim(-max_val * 0.32, max_val * 1.30)
    ax.set_ylim(-0.6, len(names) - 0.4)

    _style_axes(ax, _h('קטגוריות מובילות — YTD (סה"כ שנתי)'))

    patches = [
        mpatches.Patch(color=CLR_BUDGET, label="יעד תקציב"),
    ]
    ax.legend(handles=patches, fontsize=7, loc="lower right",
              framealpha=0, labelcolor=CLR_MUTED, handlelength=1.2)


# ── Dark-theme palette for pie / donut chart ──────────────────────────────────
_D_BG    = "#0f172a"   # page background
_D_SURF  = "#1e293b"   # card / bar track
_D_TEXT  = "#f1f5f9"   # primary labels
_D_MUTED = "#94a3b8"   # secondary labels
_D_SEP   = "#334155"   # dividers

_DONUT_COLORS = [
    "#60a5fa",  # blue-400
    "#34d399",  # emerald-400
    "#fbbf24",  # amber-400
    "#f87171",  # red-400
    "#a78bfa",  # violet-400
    "#38bdf8",  # sky-400
    "#fb923c",  # orange-400
    "#e879f9",  # fuchsia-400
    "#4ade80",  # green-400
    "#facc15",  # yellow-400
    "#64748b",  # slate (for "other")
]


def generate_pie(categories: list, month_name: str = "") -> bytes:
    """Dark-themed donut + ranked category bars."""
    active = sorted([c for c in categories if c["actual"] > 0], key=lambda x: -x["actual"])
    if not active:
        return _empty_chart()

    top  = active[:10]
    rest = active[10:]
    slices = list(top)
    if rest:
        slices.append({
            "name": f"אחר ({len(rest)})",
            "actual": sum(c["actual"] for c in rest),
            "budget": 0,
        })

    values = [c["actual"] for c in slices]
    colors = _DONUT_COLORS[:len(slices)]
    total  = sum(values)

    fig = plt.figure(figsize=(13, 7), dpi=125, facecolor=_D_BG)
    gs  = fig.add_gridspec(
        1, 2, width_ratios=[1.0, 1.25], wspace=0.06,
        left=0.01, right=0.99, top=0.91, bottom=0.04,
    )
    ax_d = fig.add_subplot(gs[0])
    ax_r = fig.add_subplot(gs[1])

    month_lbl = f" — {month_name}" if month_name else ""
    fig.suptitle("‎" + _h(f"התפלגות הוצאות{month_lbl}"),
                 fontsize=14, fontweight="bold", color=_D_TEXT,
                 x=0.5, ha="center", y=0.97)

    _draw_donut(ax_d, values, colors, total)
    _draw_category_bars(ax_r, slices, colors, total)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=125, facecolor=_D_BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _draw_donut(ax, values, colors, total):
    wedges, _ = ax.pie(
        values,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.42, "edgecolor": _D_BG, "linewidth": 3},
        radius=1,
    )
    wedges[0].set_radius(1.07)   # highlight largest slice

    # Centre annotation
    total_str = f"{int(total/1000):,}k" if total >= 10_000 else f"{int(total):,}"
    ax.text(0,  0.14, "‎" + _h("סה\"כ"), ha="center", va="center", fontsize=10, color=_D_MUTED)
    ax.text(0, -0.12, f"{total_str} ₪",
            ha="center", va="center", fontsize=20, color=_D_TEXT, fontweight="bold")

    ax.set_facecolor(_D_BG)
    ax.set_aspect("equal")


def _draw_category_bars(ax, slices, colors, total):
    ax.set_facecolor(_D_BG)
    n    = len(slices)
    ypos = np.arange(n - 1, -1, -1, dtype=float)  # top→bottom
    max_pct = max(c["actual"] / total for c in slices) or 1

    for c, clr, yi in zip(slices, colors, ypos):
        pct   = c["actual"] / total
        bar_w = pct / max_pct          # normalised 0–1

        # Track (dim background bar)
        ax.barh(yi, 1.0, height=0.38, color=_D_SURF, left=0, zorder=1, linewidth=0)
        # Coloured fill
        ax.barh(yi, bar_w, height=0.38, color=clr, alpha=0.90, left=0, zorder=2, linewidth=0)

        # Category name — left of bar
        ax.text(-0.03, yi + 0.22, "‎" + _h(c["name"][:24]),
                va="bottom", ha="left", fontsize=8.5, color=_D_TEXT, fontweight="bold",
                transform=ax.get_yaxis_transform())

        # Amount + % — right of bar (NO Hebrew here: avoids matplotlib RTL mis-detection)
        bud = c.get("budget", 0)
        if bud > 0:
            used_pct = int(c["actual"] / bud * 100)
            over = c["actual"] - bud
            if over > 0:
                status_str = f"  [!+{_fmt(over)}]"
            elif used_pct >= 75:
                status_str = f"  [{used_pct}%~]"
            else:
                status_str = f"  [{used_pct}%]"
        else:
            status_str = ""
        # ‎ (LRM) forces LTR paragraph — prevents matplotlib RTL on numbers
        label = f"‎{pct*100:.1f}%   {int(c['actual']):,} ₪{status_str}"
        ax.text(bar_w + 0.02, yi, label,
                va="center", ha="left", fontsize=7.5, color=_D_MUTED)

    ax.set_xlim(-0.01, 2.20)
    ax.set_ylim(-0.65, n - 0.35)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.spines[["top", "right", "left", "bottom"]].set_visible(False)
    ax.set_facecolor(_D_BG)


def _empty_chart() -> bytes:
    fig, ax = plt.subplots(figsize=(8, 4), dpi=120, facecolor=CLR_BG)
    ax.text(0.5, 0.5, _h("אין נתונים זמינים לדוח מגמה"),
            ha="center", va="center", fontsize=14, color=CLR_MUTED,
            transform=ax.transAxes)
    ax.set_axis_off()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor=CLR_BG)
    plt.close(fig)
    buf.seek(0)
    return buf.read()

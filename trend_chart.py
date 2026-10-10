"""Generate a trend PNG for the /trend Telegram command.

Two panels:
  TOP  — Monthly totals bar chart (actual vs budget), colored by budget status
  BOTTOM — Top-8 YTD categories horizontal bars with budget markers
"""

import io
from collections import defaultdict

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

    fig.suptitle("דוח מגמה — תקציב משפחתי", fontsize=13, fontweight="bold",
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
    ax.set_xticklabels(months, fontsize=8, color=CLR_MUTED)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: _fmt(v)))
    ax.set_xlim(-0.6, len(months) - 0.4)
    ax.set_ylim(0, max(totals + [1]) * 1.18)

    _style_axes(ax, "הוצאות חודשיות (₪)")

    # Legend
    patches = [
        mpatches.Patch(color=CLR_GREEN,  label="בתוך תקציב"),
        mpatches.Patch(color=CLR_AMBER,  label="קרוב לגבול (75%+)"),
        mpatches.Patch(color=CLR_RED,    label="חריגה"),
        mpatches.Patch(color=CLR_BUDGET, label="יעד תקציב"),
    ]
    ax.legend(handles=patches, fontsize=7, loc="upper left",
              framealpha=0, labelcolor=CLR_MUTED, handlelength=1.2)


def _draw_categories(ax, top_cats):
    if not top_cats:
        ax.text(0.5, 0.5, "אין נתוני קטגוריה", ha="center", va="center",
                color=CLR_MUTED, transform=ax.transAxes)
        _style_axes(ax, "קטגוריות מובילות — YTD")
        return

    names   = [n[:22] for n, _ in reversed(top_cats)]
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

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=8.5, color=CLR_TEXT)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: _fmt(v)))
    ax.set_xlim(0, max_val * 1.30)
    ax.set_ylim(-0.6, len(names) - 0.4)

    _style_axes(ax, "קטגוריות מובילות — YTD (סה\"כ שנתי)")

    patches = [
        mpatches.Patch(color=CLR_BUDGET, label="יעד תקציב"),
    ]
    ax.legend(handles=patches, fontsize=7, loc="lower right",
              framealpha=0, labelcolor=CLR_MUTED, handlelength=1.2)


# ── Pie chart colours (categorical) ──────────────────────────────────────────
PIE_COLORS = [
    "#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6",
    "#06b6d4", "#f97316", "#ec4899", "#14b8a6", "#6366f1",
    "#84cc16", "#e11d48",
]


def generate_pie(categories: list, month_name: str = "") -> bytes:
    """Return PNG bytes: category pie + budget-utilisation 'where to save' bars."""
    active = sorted([c for c in categories if c["actual"] > 0], key=lambda x: -x["actual"])
    if not active:
        return _empty_chart()

    TOP_N   = 9
    top     = active[:TOP_N]
    rest    = active[TOP_N:]
    slices  = list(top)
    if rest:
        slices.append({
            "name": f"אחר ({len(rest)})",
            "actual": sum(c["actual"] for c in rest),
            "budget": 0,
        })

    labels  = [c["name"][:22] for c in slices]
    values  = [c["actual"]    for c in slices]
    colors  = PIE_COLORS[:len(slices)]

    budgeted = sorted(
        [c for c in active if c.get("budget", 0) > 0],
        key=lambda x: -(x["actual"] / x["budget"]),
    )[:10]

    fig = plt.figure(figsize=(13, 7), dpi=120, facecolor=CLR_BG)
    gs  = fig.add_gridspec(
        1, 2, width_ratios=[1.3, 1], wspace=0.30,
        left=0.02, right=0.97, top=0.90, bottom=0.04,
    )
    ax_pie = fig.add_subplot(gs[0])
    ax_bud = fig.add_subplot(gs[1])

    title = f"התפלגות הוצאות — {month_name}" if month_name else "התפלגות הוצאות"
    fig.suptitle(title, fontsize=13, fontweight="bold", color=CLR_TEXT, x=0.5, ha="center")

    _draw_pie_panel(ax_pie, labels, values, colors)
    _draw_budget_utilization(ax_bud, budgeted)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor=CLR_BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _draw_pie_panel(ax, labels, values, colors):
    total = sum(values) or 1

    def _autopct(pct):
        return f"{pct:.1f}%" if pct >= 4 else ""

    wedges, _texts, autotexts = ax.pie(
        values,
        labels=None,
        colors=colors,
        autopct=_autopct,
        pctdistance=0.78,
        startangle=90,
        wedgeprops={"linewidth": 1.5, "edgecolor": CLR_BG},
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color(CLR_BG)
        at.set_fontweight("bold")

    legend_labels = [f"{lbl}: {_fmt(v)} ₪  ({v/total*100:.1f}%)" for lbl, v in zip(labels, values)]
    ax.legend(
        wedges, legend_labels,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.20),
        fontsize=7.5,
        framealpha=0,
        labelcolor=CLR_TEXT,
        ncol=2,
    )
    ax.text(0, 0, f"סה\"כ\n{_fmt(total)} ₪",
            ha="center", va="center", fontsize=9, fontweight="bold", color=CLR_TEXT)
    ax.set_title("התפלגות קטגוריות", fontsize=10, fontweight="bold", color=CLR_TEXT, pad=8)


def _draw_budget_utilization(ax, budgeted):
    if not budgeted:
        ax.text(0.5, 0.5, "אין תקציבים מוגדרים",
                ha="center", va="center", color=CLR_MUTED,
                transform=ax.transAxes, fontsize=10)
        ax.set_axis_off()
        return

    names   = [c["name"][:22] for c in reversed(budgeted)]
    actuals = [c["actual"]    for c in reversed(budgeted)]
    budgets = [c["budget"]    for c in reversed(budgeted)]
    pcts    = [a / b for a, b in zip(actuals, budgets)]
    colors  = [_status_color(a, b) for a, b in zip(actuals, budgets)]
    y       = np.arange(len(names))

    ax.barh(y, [min(p, 1.35) for p in pcts], height=0.6, color=colors, zorder=3, linewidth=0)
    ax.axvline(x=1.0, color=CLR_RED, linewidth=1.5, zorder=4, linestyle="--", alpha=0.6)

    for yi, (a, b, p) in enumerate(zip(actuals, budgets, pcts)):
        rem = b - a
        pct_int = int(p * 100)
        if rem < 0:
            label = f"{_fmt(a)}/{_fmt(b)} (+{_fmt(-rem)} חריגה)"
        else:
            label = f"{_fmt(a)}/{_fmt(b)} ({pct_int}%)"
        ax.text(min(p, 1.35) + 0.02, yi, label,
                va="center", ha="left", fontsize=7, color=CLR_TEXT)

    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=8, color=CLR_TEXT)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v*100)}%"))
    ax.set_xlim(0, 1.85)
    ax.set_ylim(-0.6, len(names) - 0.4)
    ax.set_xlabel("ניצול תקציב", fontsize=8, color=CLR_MUTED)

    _style_axes(ax, "איפה לחסוך — ניצול תקציב")


def _empty_chart() -> bytes:
    fig, ax = plt.subplots(figsize=(8, 4), dpi=120, facecolor=CLR_BG)
    ax.text(0.5, 0.5, "אין נתונים זמינים לדוח מגמה",
            ha="center", va="center", fontsize=14, color=CLR_MUTED,
            transform=ax.transAxes)
    ax.set_axis_off()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor=CLR_BG)
    plt.close(fig)
    buf.seek(0)
    return buf.read()

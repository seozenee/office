"""Matplotlib chart rendering (used for DOCX/PDF images). PPTX/XLSX use native charts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

_KO_FONTS = ["NanumGothic", "NanumBarunGothic", "Malgun Gothic", "Noto Sans CJK KR", "AppleGothic", "Unifont"]
_available = {f.name for f in font_manager.fontManager.ttflist}
_font = next((f for f in _KO_FONTS if f in _available), None)
if _font:
    plt.rcParams["font.family"] = _font
plt.rcParams["axes.unicode_minus"] = False

PALETTE = ["#2B5DAA", "#E07B39", "#1F7A4D", "#8A4FBF", "#C0392B", "#7F8C8D"]


def render_chart_png(spec: dict[str, Any], path: Path) -> Path:
    kind = spec.get("kind", "bar")
    cats = [str(c) for c in spec.get("categories", [])]
    series = spec.get("series", [])
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    if kind == "pie" and series:
        ax.pie(series[0]["values"], labels=cats, autopct="%1.0f%%", colors=PALETTE[: len(cats)])
        ax.axis("equal")
    else:
        n = max(len(series), 1)
        width = 0.8 / n
        for i, s in enumerate(series):
            xs = [x + (i - (n - 1) / 2) * width for x in range(len(cats))] if kind == "bar" else list(range(len(cats)))
            if kind == "line":
                ax.plot(xs, s["values"], marker="o", label=s["name"], color=PALETTE[i % len(PALETTE)])
            else:
                ax.bar(xs, s["values"], width=width, label=s["name"], color=PALETTE[i % len(PALETTE)])
        ax.set_xticks(range(len(cats)))
        ax.set_xticklabels(cats)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.3)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        if len(series) > 1:
            ax.legend(frameon=False)
    if spec.get("title"):
        ax.set_title(spec["title"], fontsize=12)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path

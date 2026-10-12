# -*- coding: utf-8 -*-
"""
estilo_graficos.py

Estilo único para os gráficos dos notebooks de Machine Learning: mesma
paleta (validada para daltonismo), eixos discretos e textos legíveis.
"""

import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap

# Paleta categórica - usar SEMPRE nesta ordem (a ordem é o que garante a
# distinção para daltônicos). Com 4+ grupos no mesmo gráfico de pontos,
# combinar cor com MARCADORES diferentes.
CORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
MARCADORES = ["o", "s", "^", "D", "v", "P", "X", "*"]

TINTA = "#0b0b0b"
TINTA_SECUNDARIA = "#52514e"
TINTA_SUAVE = "#898781"
GRADE = "#e1e0d9"
EIXO = "#c3c2b7"
FUNDO = "#fcfcfb"
NEUTRO = "#c3c2b7"

# Sequencial (magnitude): um só tom, do claro ao escuro
SEQUENCIAL = LinearSegmentedColormap.from_list(
    "azul", ["#f0efec", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
# Divergente (acima/abaixo da média): azul <-> cinza <-> vermelho
DIVERGENTE = LinearSegmentedColormap.from_list(
    "diverge", ["#e34948", "#f0efec", "#2a78d6"])


def aplicar_estilo():
    mpl.rcParams.update({
        "figure.facecolor": FUNDO,
        "axes.facecolor": FUNDO,
        "savefig.facecolor": FUNDO,
        "figure.dpi": 110,
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.titlepad": 12,
        "axes.labelcolor": TINTA_SECUNDARIA,
        "axes.edgecolor": EIXO,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRADE,
        "grid.linewidth": 0.6,
        "xtick.color": TINTA_SUAVE,
        "ytick.color": TINTA_SUAVE,
        "xtick.labelcolor": TINTA_SECUNDARIA,
        "ytick.labelcolor": TINTA_SECUNDARIA,
        "text.color": TINTA,
        "legend.frameon": False,
        "lines.linewidth": 2,
        "lines.markersize": 7,
        "axes.prop_cycle": mpl.cycler(color=CORES),
    })


def rotular_barras(ax, barras, formato="{:.0f}"):
    """Escreve o valor na ponta de cada barra (texto na cor da tinta, não da série)."""
    ax.bar_label(barras, fmt=formato, padding=3, color=TINTA_SECUNDARIA, fontsize=9)

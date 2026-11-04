# model/formula/lut.py
"""
Tables de correspondance (look-up tables) dans les formules :
    steps(x; x1; y1; x2; y2; ...)    paliers : y1 à partir de x1, y2 à partir de x2...
    interp(x; x1; y1; x2; y2; ...)   interpolation linéaire entre les points
Avant le premier point : valeur manquante (nan) ; après le dernier : dernière valeur.
x est quelconque : time (ex: puissance du convertisseur par paliers) ou une voie
(ex: courbe d'étalonnage d'un capteur).
"""
import numpy as np

from .errors import FormulaError

LUT_FUNCTIONS = ("steps", "interp")


def check_table(name: str, args: list) -> tuple[np.ndarray, np.ndarray]:
    """(abscisses, valeurs) de la table : nombres, abscisses strictement croissantes."""
    if len(args) < 3 or len(args) % 2 == 0:
        raise FormulaError(f"Function '{name}' expects x then pairs of values: "
                           f"{name}(x; x1; y1; x2; y2...)")
    points = args[1:]
    if any(np.ndim(p) != 0 for p in points):
        raise FormulaError(f"Function '{name}': the table must contain numbers only")
    xs = np.array(points[0::2], dtype=float)
    ys = np.array(points[1::2], dtype=float)
    if not np.isfinite(xs).all():
        raise FormulaError(f"Function '{name}': undefined breakpoint (nan / inf)")
    if np.any(np.diff(xs) <= 0):
        raise FormulaError(f"Function '{name}': the breakpoints must be strictly "
                           f"increasing ({'; '.join(f'{v:g}' for v in xs)})")
    return xs, ys


def steps(x, xs: np.ndarray, ys: np.ndarray):
    """Paliers : valeur du dernier point d'abscisse <= x."""
    x = np.asarray(x, dtype=float)
    index = np.searchsorted(xs, x, side="right") - 1
    values = ys[np.clip(index, 0, None)]
    return np.where((index >= 0) & ~np.isnan(x), values, np.nan)


def interp(x, xs: np.ndarray, ys: np.ndarray):
    """Interpolation linéaire entre les points."""
    return np.interp(np.asarray(x, dtype=float), xs, ys, left=np.nan, right=ys[-1])


def parse_number(text: str) -> float:
    """Nombre saisi ou collé (virgule décimale admise) ; ValueError sinon."""
    value = float(text.strip().replace(",", ".").replace(" ", "").replace(" ", ""))
    if not np.isfinite(value):
        raise ValueError(text)
    return value


def parse_rows(text: str) -> list[tuple[float, float]]:
    """
    Lignes (x, valeur) d'un texte collé depuis Excel : colonnes séparées par une
    tabulation, un « ; » ou des espaces, virgule décimale admise. Une première ligne
    non numérique (en-tête) est ignorée ; les colonnes au-delà de la 2e aussi.
    """
    rows = []
    lines = [line for line in text.splitlines() if line.strip()]
    for n, line in enumerate(lines, start=1):
        for sep in ("\t", ";"):
            if sep in line:
                cells = line.split(sep)
                break
        else:
            cells = line.split()
        try:
            if len(cells) < 2:
                raise ValueError(line)
            rows.append((parse_number(cells[0]), parse_number(cells[1])))
        except ValueError:
            if n == 1:
                continue                                    # en-tête
            raise ValueError(f"Ligne {n} : « {line.strip()} » n'est pas une paire "
                             "de nombres") from None
    return rows


def format_number(value: float) -> str:
    """Nombre tel qu'écrit dans une formule (lu par le lexer)."""
    return format(float(value), ".10g")


def format_call(name: str, x: str, rows) -> str:
    """Appel de fonction inséré dans une formule : steps(time; 0; 200; 201; 800)."""
    values = [format_number(v) for row in rows for v in row]
    return f"{name}({'; '.join([x] + values)})"

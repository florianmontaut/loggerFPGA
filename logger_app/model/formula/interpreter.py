
from functools import reduce
import numpy as np
from .nodes import *
from .values import *
from .errors import FormulaError
from . import fluids, lut

CONSTANTS = {'pi': np.pi, 'e': np.e}

# Une valeur est soit un float (scalaire), soit un np.ndarray (signal).
#  - Scalaires : une erreur de domaine (log(-1), sqrt(-1), 1/0, overflow...) lève une exception.
#  - Tableaux  : sémantique numpy, les échantillons invalides donnent nan / inf sans interrompre le calcul.

def to_value(x):
    arr = np.asarray(x, dtype=float)
    return float(arr) if arr.ndim == 0 else arr

def all_finite(values):
    return all(np.all(np.isfinite(v)) for v in values)

def _reduce_or_elementwise(single, elementwise):
    # 1 argument  : réduction sur le signal       -> max(CH1) = valeur crête
    # n arguments : élément par élément entre eux -> max(CH1;0) = CH1 écrêté à 0
    return lambda x: single(x[0]) if len(x) == 1 else reduce(elementwise, x)

def _nan_reduction(fn):
    # réduction sur les seules valeurs définies ; nan si aucune ne l'est (nansum
    # renverrait 0 pour un signal entièrement manquant)
    def reduction(x):
        if np.all(np.isnan(x)):
            return np.nan
        return fn(x)
    return reduction

class Interpreter:
    def __init__(self): self.vars = dict(CONSTANTS)

    def visit(self, node):
        method = getattr(self, f"visit_{type(node).__name__}")
        return method(node)

    def compute(self, name, fn, inputs):
        with np.errstate(all='ignore'):
            try:
                result = to_value(fn(inputs))
            except (ValueError, TypeError) as e:
                raise FormulaError(f"Error in '{name}': {e}")
        if np.ndim(result) == 0 and not np.isfinite(result) and all_finite(inputs):
            raise FormulaError(f"Math error in '{name}'")
        return Number(result)

    def visit_NumberNode(self, node): return Number(node.value)

    def visit_VariableNode(self, node):
        if node.name not in self.vars: raise FormulaError(f"Undefined variable '{node.name}'")
        return Number(to_value(self.vars[node.name]))

    def visit_ChannelNode(self, node):
        # les voies sont fournies dans vars sous la clé « [nom] » (voir formula.evaluate)
        key = f"[{node.name}]"
        if key not in self.vars: raise FormulaError(f"Unknown channel '{key}'")
        return Number(to_value(self.vars[key]))

    def visit_AssignmentNode(self, node):
        value = self.visit(node.expr).value
        self.vars[node.name] = value
        return Number(value)

    def visit_binary(self, name, fn, node):
        a, b = self.visit(node.node_a).value, self.visit(node.node_b).value
        return self.compute(name, lambda x: fn(x[0], x[1]), [a, b])

    def visit_AddNode(self, node): return self.visit_binary('+', np.add, node)
    def visit_SubtractNode(self, node): return self.visit_binary('-', np.subtract, node)
    def visit_MultiplyNode(self, node): return self.visit_binary('*', np.multiply, node)
    def visit_PowerNode(self, node): return self.visit_binary('^', np.power, node)

    def visit_DivideNode(self, node):
        a, b = self.visit(node.node_a).value, self.visit(node.node_b).value
        if np.ndim(b) == 0 and b == 0: raise FormulaError("Division by zero")
        return self.compute('/', lambda x: np.divide(x[0], x[1]), [a, b])

    def visit_PlusNode(self, node): return Number(self.visit(node.node).value)
    def visit_MinusNode(self, node): return Number(-self.visit(node.node).value)

    def visit_FuncNode(self, node):
        func = node.func.lower()
        args = [self.visit(a).value for a in node.args]

        # pi() et e() restent acceptés en plus de pi et e
        if func in CONSTANTS and not args: return Number(CONSTANTS[func])

        # nom -> (fonction, nombre d'arguments ; None = au moins 1)
        table = {
            'sin': (lambda x: np.sin(x[0]), 1),
            'cos': (lambda x: np.cos(x[0]), 1),
            'tan': (lambda x: np.tan(x[0]), 1),
            'exp': (lambda x: np.exp(x[0]), 1),
            'log': (lambda x: np.log(x[0]), 1),
            'log10': (lambda x: np.log10(x[0]), 1),
            'sqrt': (lambda x: np.sqrt(x[0]), 1),
            'abs': (lambda x: np.abs(x[0]), 1),
            # réductions : données manquantes (nan) ignorées ; élément par élément, un
            # échantillon manquant reste manquant
            'max': (_reduce_or_elementwise(_nan_reduction(np.nanmax), np.maximum), None),
            'min': (_reduce_or_elementwise(_nan_reduction(np.nanmin), np.minimum), None),
            'sum': (_reduce_or_elementwise(_nan_reduction(np.nansum), np.add), None),
            'avg': (lambda x: _nan_reduction(np.nanmean)(x[0]) if len(x) == 1
                              else reduce(np.add, x) / len(x), None)
        }

        if func in lut.LUT_FUNCTIONS:
            # table de correspondance : vérifiée avant le calcul (message explicite)
            xs, ys = lut.check_table(func, args)
            evaluate = getattr(lut, func)
            return self.compute(func, lambda x: evaluate(x[0], xs, ys), args[:1])

        if func in fluids.PROPERTIES:
            # caloporteur : propriété à la température donnée (°C)
            if len(args) != 1:
                raise FormulaError(f"Function '{func}' expects 1 argument (temperature in °C), "
                                   f"got {len(args)}")
            return self.compute(func, lambda x: fluids.evaluate(func, x[0]), args)

        if func not in table:
            raise FormulaError(f"Unknown function '{func}'")

        fn, arity = table[func]
        if arity is None and not args:
            raise FormulaError(f"Function '{func}' expects at least 1 argument")
        if arity is not None and len(args) != arity:
            raise FormulaError(f"Function '{func}' expects {arity} argument(s), got {len(args)}")

        return self.compute(func, fn, args)

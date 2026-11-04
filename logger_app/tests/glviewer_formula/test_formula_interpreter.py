
import unittest
import math

from model.formula.nodes import *
from model.formula.interpreter import Interpreter
from model.formula.values import Number


class TestInterpreter(unittest.TestCase):

    # ---------------------------
    # Tests de base
    # ---------------------------
    def test_numbers(self):
        value = Interpreter().visit(NumberNode(51.2))
        self.assertEqual(value.value, 51.2)

    def test_unary_nodes(self):
        interp = Interpreter()
        self.assertEqual(interp.visit(PlusNode(NumberNode(10))).value, 10)
        self.assertEqual(interp.visit(MinusNode(NumberNode(10))).value, -10)

    def test_basic_operations(self):
        interp = Interpreter()

        self.assertEqual(interp.visit(AddNode(NumberNode(51.2), NumberNode(48.8))).value, 100.0)
        self.assertEqual(interp.visit(SubtractNode(NumberNode(51), NumberNode(48))).value, 3)
        self.assertEqual(interp.visit(MultiplyNode(NumberNode(5), NumberNode(6))).value, 30)
        self.assertEqual(interp.visit(PowerNode(NumberNode(2), NumberNode(3))).value, 8)

        self.assertAlmostEqual(
            interp.visit(DivideNode(NumberNode(51.2), NumberNode(48.8))).value,
            1.04918,
            5
        )

        with self.assertRaises(Exception):
            interp.visit(DivideNode(NumberNode(10), NumberNode(0)))

    def test_full_expression(self):
        interp = Interpreter()
        value = interp.visit(
            AddNode(
                NumberNode(27.0),
                MultiplyNode(
                    SubtractNode(
                        DivideNode(NumberNode(43.0), NumberNode(36)),
                        NumberNode(48.0)
                    ),
                    NumberNode(51.0)
                )
            )
        )
        self.assertAlmostEqual(value.value, -2360.083333, 5)

    # ---------------------------
    # Tests des fonctions simples
    # ---------------------------
    def test_math_functions(self):
        interp = Interpreter()

        self.assertAlmostEqual(
            interp.visit(FuncNode("sin", [NumberNode(math.pi/2)])).value,
            1.0, 5
        )
        self.assertEqual(interp.visit(FuncNode("abs", [NumberNode(-5)])).value, 5)
        self.assertEqual(interp.visit(FuncNode("sqrt", [NumberNode(9)])).value, 3)
        self.assertAlmostEqual(
            interp.visit(FuncNode("log", [NumberNode(math.e)])).value,
            1.0, 5
        )

        with self.assertRaises(Exception):
            interp.visit(FuncNode("unknown_function", [NumberNode(5)]))

    def test_function_arity(self):
        interp = Interpreter()
        with self.assertRaises(Exception):
            interp.visit(FuncNode("sin", []))
        with self.assertRaises(Exception):
            interp.visit(FuncNode("sin", [NumberNode(1), NumberNode(2)]))
        with self.assertRaises(Exception):
            interp.visit(FuncNode("max", []))
        with self.assertRaises(Exception):
            interp.visit(FuncNode("avg", []))
        with self.assertRaises(Exception):
            interp.visit(FuncNode("sqrt", [NumberNode(-1)]))

    def test_scalar_domain_errors(self):
        # en scalaire, les erreurs de domaine lèvent toujours une exception
        interp = Interpreter()
        for node in [FuncNode("log", [NumberNode(0)]),
                     FuncNode("log", [NumberNode(-1)]),
                     FuncNode("exp", [NumberNode(1000)]),
                     PowerNode(NumberNode(-8), NumberNode(1/3)),
                     DivideNode(NumberNode(0), NumberNode(0))]:
            with self.assertRaises(Exception):
                interp.visit(node)

    def test_constants_as_variables(self):
        interp = Interpreter()
        self.assertAlmostEqual(interp.visit(VariableNode("pi")).value, math.pi, 7)
        self.assertAlmostEqual(interp.visit(VariableNode("e")).value, math.e, 7)

    # ---------------------------
    # Tests des constantes
    # ---------------------------
    def test_constants(self):
        interp = Interpreter()

        self.assertAlmostEqual(
            interp.visit(FuncNode("pi", [])).value,
            math.pi,
            7
        )
        self.assertAlmostEqual(
            interp.visit(FuncNode("e", [])).value,
            math.e,
            7
        )

    # ---------------------------
    # Tests fonctions multi-arguments
    # ---------------------------
    def test_multi_argument_functions(self):
        interp = Interpreter()

        self.assertEqual(
            interp.visit(FuncNode("max", [NumberNode(1), NumberNode(5), NumberNode(3)])).value,
            5
            )
        self.assertEqual(
            interp.visit(FuncNode("min", [NumberNode(10), NumberNode(7), NumberNode(9)])).value,
            7
            )
        self.assertEqual(
            interp.visit(FuncNode("sum", [NumberNode(1), NumberNode(2), NumberNode(3), NumberNode(4)])).value,
            10
            )
        self.assertEqual(
            interp.visit(FuncNode("avg", [NumberNode(10), NumberNode(20), NumberNode(30)])).value,
            20
            )

    # ---------------------------
    # Tests variables
    # ---------------------------
    def test_variables(self):
        interp = Interpreter()

        # assignment
        assign = AssignmentNode("x", NumberNode(42))
        result = interp.visit(assign)
        self.assertEqual(result.value, 42)
        self.assertEqual(interp.vars["x"], 42)

        # usage
        value = interp.visit(VariableNode("x"))
        self.assertEqual(value.value, 42)

        # error: undefined variable
        with self.assertRaises(Exception):
            interp.visit(VariableNode("unknown_var"))

    # ---------------------------
    # Test d'expressions combinées
    # ---------------------------
    def test_combined_expressions(self):
        interp = Interpreter()

        # x = 5
        interp.visit(AssignmentNode("x", NumberNode(5)))

        # sin(x) + max(1,2,3) * sqrt(9)
        expr = AddNode(
            FuncNode("sin", [VariableNode("x")]),
            MultiplyNode(
                FuncNode("max", [NumberNode(1), NumberNode(2), NumberNode(3)]),
                FuncNode("sqrt", [NumberNode(9)])
            )
        )

        value = interp.visit(expr).value

        expected = math.sin(5) + 3 * 3
        self.assertAlmostEqual(value, expected, 5)


if __name__ == "__main__":
    unittest.main()

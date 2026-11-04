import unittest
from model.formula.tokens import Token, TokenType
from model.formula.parser import MathParser
from model.formula.nodes import *

class TestParser(unittest.TestCase):

    def test_empty(self):
        tokens = []
        node = MathParser(tokens).parse()
        self.assertEqual(node,None)

    def test_numbers(self):
        tokens = [Token(TokenType.NUMBER,51.2)]
        node = MathParser(tokens).parse()
        self.assertEqual(node,NumberNode(51.2))

    def test_individual_operations(self):
        tokens = [
                Token(TokenType.NUMBER,51.2),
                Token(TokenType.PLUS),
                Token(TokenType.NUMBER,48.8)
                ]
        node = MathParser(tokens).parse()
        self.assertEqual(node,AddNode(NumberNode(51.2),NumberNode(48.8)))
        tokens = [
                Token(TokenType.NUMBER,51.2),
                Token(TokenType.MINUS),
                Token(TokenType.NUMBER,48.8)
                ]
        node = MathParser(tokens).parse()
        self.assertEqual(node,SubtractNode(NumberNode(51.2),NumberNode(48.8)))
        tokens = [
                Token(TokenType.NUMBER,51.2),
                Token(TokenType.MULTIPLY),
                Token(TokenType.NUMBER,48.8)
                ]
        node = MathParser(tokens).parse()
        self.assertEqual(node,MultiplyNode(NumberNode(51.2),NumberNode(48.8)))
        tokens = [
                Token(TokenType.NUMBER,51.2),
                Token(TokenType.DIVIDE),
                Token(TokenType.NUMBER,48.8)
                ]
        node = MathParser(tokens).parse()
        self.assertEqual(node,DivideNode(NumberNode(51.2),NumberNode(48.8)))

        tokens = [
                    Token(TokenType.FUNC,'sin'),
                    Token(TokenType.LPAREN),
                    Token(TokenType.FUNC,'pi'),
                    Token(TokenType.DIVIDE),
                    Token(TokenType.NUMBER, 2.0),
                    Token(TokenType.RPAREN),
                    Token(TokenType.MULTIPLY),
                    Token(TokenType.NUMBER, 5.0),
                ]
        node = MathParser(tokens).parse()
        self.assertEqual(node,MultiplyNode(FuncNode('sin',[DivideNode(VariableNode('pi'),NumberNode(2.0))]),NumberNode(5)))
        
    def test_full_expression(self):
        tokens = [
            Token(TokenType.NUMBER, 27.0),
            Token(TokenType.PLUS),
            Token(TokenType.LPAREN),
            Token(TokenType.NUMBER, 43.0),
            Token(TokenType.DIVIDE),
            Token(TokenType.NUMBER,36.0),
            Token(TokenType.MINUS),
            Token(TokenType.NUMBER,48.0),
            Token(TokenType.RPAREN),
            Token(TokenType.MULTIPLY),
            Token(TokenType.NUMBER,51.0)
        ]
        node = MathParser(tokens).parse()
        self.assertEqual(node,AddNode(
                                NumberNode(27.0),
                                    MultiplyNode(
                                        SubtractNode(DivideNode(
                                                        NumberNode(43.0),
                                                        NumberNode(36)),
                                                    NumberNode(48.0)),
                                        NumberNode(51.0))))

        "27 + (43 / 36 - 48) * 51"

    def test_function_and_variable_names_kept(self):
        # log(x) ne doit pas perdre le nom 'log', x+5 ne doit pas perdre 'x'
        tokens = [Token(TokenType.FUNC,'log'), Token(TokenType.LPAREN), Token(TokenType.NUMBER,1.0), Token(TokenType.RPAREN)]
        self.assertEqual(MathParser(tokens).parse(), FuncNode('log',[NumberNode(1.0)]))
        tokens = [Token(TokenType.FUNC,'x'), Token(TokenType.PLUS), Token(TokenType.NUMBER,5.0)]
        self.assertEqual(MathParser(tokens).parse(), AddNode(VariableNode('x'),NumberNode(5.0)))

    def test_assignment(self):
        tokens = [Token(TokenType.FUNC,'x'), Token(TokenType.ASSIGN), Token(TokenType.NUMBER,5.0)]
        self.assertEqual(MathParser(tokens).parse(), AssignmentNode('x',NumberNode(5.0)))

    def test_power(self):
        # 2^3
        tokens = [Token(TokenType.NUMBER,2.0), Token(TokenType.POWER), Token(TokenType.NUMBER,3.0)]
        self.assertEqual(MathParser(tokens).parse(), PowerNode(NumberNode(2.0),NumberNode(3.0)))
        # 2^3^2 -> associatif à droite
        tokens = [Token(TokenType.NUMBER,2.0), Token(TokenType.POWER), Token(TokenType.NUMBER,3.0),
                  Token(TokenType.POWER), Token(TokenType.NUMBER,2.0)]
        self.assertEqual(MathParser(tokens).parse(),
                         PowerNode(NumberNode(2.0),PowerNode(NumberNode(3.0),NumberNode(2.0))))
        # -2^2 -> -(2^2)
        tokens = [Token(TokenType.MINUS), Token(TokenType.NUMBER,2.0), Token(TokenType.POWER), Token(TokenType.NUMBER,2.0)]
        self.assertEqual(MathParser(tokens).parse(), MinusNode(PowerNode(NumberNode(2.0),NumberNode(2.0))))
        # 2*3^2 -> 2*(3^2)
        tokens = [Token(TokenType.NUMBER,2.0), Token(TokenType.MULTIPLY), Token(TokenType.NUMBER,3.0),
                  Token(TokenType.POWER), Token(TokenType.NUMBER,2.0)]
        self.assertEqual(MathParser(tokens).parse(),
                         MultiplyNode(NumberNode(2.0),PowerNode(NumberNode(3.0),NumberNode(2.0))))

    def test_multi_args(self):
        tokens = [Token(TokenType.FUNC,'max'), Token(TokenType.LPAREN), Token(TokenType.NUMBER,1.0),
                  Token(TokenType.DELIMITOR), Token(TokenType.NUMBER,2.0), Token(TokenType.RPAREN)]
        self.assertEqual(MathParser(tokens).parse(), FuncNode('max',[NumberNode(1.0),NumberNode(2.0)]))

    def test_syntax_errors(self):
        cases = [
            [Token(TokenType.NUMBER,1.0), Token(TokenType.NUMBER,2.0)],                       # jeton en trop
            [Token(TokenType.NUMBER,1.0), Token(TokenType.PLUS)],                             # fin prématurée
            [Token(TokenType.LPAREN), Token(TokenType.NUMBER,1.0)],                           # ')' manquante
            [Token(TokenType.FUNC,'sin'), Token(TokenType.LPAREN), Token(TokenType.NUMBER,1.0)],
            [Token(TokenType.RPAREN)],
        ]
        for tokens in cases:
            with self.assertRaises(Exception) as ctx:
                MathParser(tokens).parse()
            self.assertTrue(str(ctx.exception).startswith("Invalid syntax"), str(ctx.exception))

    def test_error_message(self):
        with self.assertRaises(Exception) as ctx:
            MathParser([]).raise_error()
        self.assertEqual(str(ctx.exception), "Invalid syntax")
        with self.assertRaises(Exception) as ctx:
            MathParser([]).raise_error("Missing ')'")
        self.assertEqual(str(ctx.exception), "Invalid syntax: Missing ')'")


if __name__ == "__main__":
    unittest.main()

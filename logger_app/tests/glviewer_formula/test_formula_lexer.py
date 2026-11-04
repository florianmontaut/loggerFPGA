import unittest
from model.formula.tokens import Token, TokenType
from model.formula.lexer import Lexer

class TestLexer(unittest.TestCase):

    def test_empty(self):
        tokens = list (Lexer("").generate_tokens())
        self.assertEqual(tokens,[])


    def test_empties(self):
        tokens = list(Lexer(" ").generate_tokens())
        self.assertEqual(tokens,[])


    def test_numbers(self):
        tokens = list(Lexer("123 123.456 123. .456 . ").generate_tokens())
        self.assertEqual(tokens,[
            Token(TokenType.NUMBER, 123.000),
            Token(TokenType.NUMBER, 123.456),
            Token(TokenType.NUMBER, 123.000),
            Token(TokenType.NUMBER, 000.456),
            Token(TokenType.NUMBER, 000.000)
        ])

    def test_operators(self):
        tokens = list(Lexer("+-*/").generate_tokens())
        self.assertEqual(tokens,[
            Token(TokenType.PLUS),
            Token(TokenType.MINUS),
            Token(TokenType.MULTIPLY),
            Token(TokenType.DIVIDE)
        ])

    def test_parens(self):
        tokens = list(Lexer("()").generate_tokens())
        self.assertEqual(tokens,[
            Token(TokenType.LPAREN),
            Token(TokenType.RPAREN)
            ])

    def test_func(self):
        tokens = list(Lexer('sin pi abs').generate_tokens())
        self.assertEqual(tokens, [
                                    Token(TokenType.FUNC, 'sin'),         
                                    Token(TokenType.FUNC, 'pi'),     
                                    Token(TokenType.FUNC, 'abs'),     
                                ]
                                )
    
    
    def test_identifiers_with_digits(self):
        tokens = list(Lexer('CH1-CH2 v_2').generate_tokens())
        self.assertEqual(tokens, [
            Token(TokenType.FUNC, 'CH1'),
            Token(TokenType.MINUS),
            Token(TokenType.FUNC, 'CH2'),
            Token(TokenType.FUNC, 'v_2'),
        ])
        # un chiffre en tête reste un nombre
        self.assertEqual(list(Lexer('2x').generate_tokens()),
                         [Token(TokenType.NUMBER, 2.0), Token(TokenType.FUNC, 'x')])

    def test_power_and_misc(self):
        tokens = list(Lexer('^;=').generate_tokens())
        self.assertEqual(tokens, [Token(TokenType.POWER), Token(TokenType.DELIMITOR), Token(TokenType.ASSIGN)])

    def test_whitespace_variants(self):
        tokens = list(Lexer('1\t+\n2\r').generate_tokens())
        self.assertEqual(tokens, [Token(TokenType.NUMBER, 1.0), Token(TokenType.PLUS), Token(TokenType.NUMBER, 2.0)])

    def test_illegal_character(self):
        # ne doit pas boucler à l'infini
        with self.assertRaises(Exception):
            list(Lexer('5 # 3').generate_tokens())
        with self.assertRaises(Exception):
            list(Lexer('3 $').generate_tokens())

    def test_all(self):
        tokens = list(Lexer("27 + (43 / 36 - 48) * 51").generate_tokens())
        self.assertEqual(tokens,[
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
        ])
        tokens = list(Lexer("x=sin(pi/2)*5").generate_tokens())
        self.assertEqual(tokens,[
            Token(TokenType.FUNC,'x'),
            Token(TokenType.ASSIGN),
            Token(TokenType.FUNC,'sin'),
            Token(TokenType.LPAREN),
            Token(TokenType.FUNC,'pi'),
            Token(TokenType.DIVIDE),
            Token(TokenType.NUMBER, 2.0),
            Token(TokenType.RPAREN),
            Token(TokenType.MULTIPLY),
            Token(TokenType.NUMBER, 5.0),
            ])


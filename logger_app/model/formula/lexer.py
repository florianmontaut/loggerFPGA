
from .tokens import Token, TokenType
from .errors import FormulaError

WHITESPACE = ' \t\n\r'
DIGITS = '0123456789'
LETTERS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_'

class Lexer:
    def __init__(self, text):
        self.text = iter(text)
        self.advance()

    def advance(self):
        try:
            self.current_char = next(self.text)
        except StopIteration:
            self.current_char = None

    def generate_tokens(self):
        while self.current_char is not None:
            if self.current_char in WHITESPACE:
                self.advance()
            elif self.current_char in DIGITS or self.current_char == '.':
                yield self.generate_number()
            elif self.current_char in LETTERS:
                yield self.generate_identifier()
            elif self.current_char == '+':
                self.advance(); yield Token(TokenType.PLUS)
            elif self.current_char == '-':
                self.advance(); yield Token(TokenType.MINUS)
            elif self.current_char == '*':
                self.advance(); yield Token(TokenType.MULTIPLY)
            elif self.current_char == '/':
                self.advance(); yield Token(TokenType.DIVIDE)
            elif self.current_char == '^':
                self.advance(); yield Token(TokenType.POWER)
            elif self.current_char == '(':
                self.advance(); yield Token(TokenType.LPAREN)
            elif self.current_char == ')':
                self.advance(); yield Token(TokenType.RPAREN)
            elif self.current_char == ';':
                self.advance(); yield Token(TokenType.DELIMITOR)
            elif self.current_char == '=':
                self.advance(); yield Token(TokenType.ASSIGN)
            elif self.current_char == '[':
                yield self.generate_channel()
            else:
                raise FormulaError(f"Illegal character: '{self.current_char}'")

    def generate_number(self):
        decimal_count = 0
        num_str = self.current_char
        self.advance()
        while self.current_char is not None and (self.current_char in DIGITS or self.current_char == '.'):
            if self.current_char == '.':
                decimal_count += 1
                if decimal_count > 1:
                    break
            num_str += self.current_char
            self.advance()
        if num_str.startswith('.'):
            num_str = '0' + num_str
        if num_str.endswith('.'):
            num_str += '0'
        num_str += self.generate_exponent()
        return Token(TokenType.NUMBER, float(num_str))

    def generate_exponent(self):
        # 4.18e3, 1E-3 : 'e' suivi d'un chiffre (ou d'un signe puis d'un chiffre) ;
        # sinon 'e' reste un identifiant (2e = 2 suivi de e : erreur du parser)
        if self.current_char is None or self.current_char not in 'eE':
            return ""
        rest = list(self.text)          # lecture anticipée (le texte est un itérateur)
        sign = rest[0] if rest and rest[0] in '+-' else ""
        digits_at = 1 if sign else 0
        if len(rest) <= digits_at or rest[digits_at] not in DIGITS:
            self.text = iter(rest)
            return ""
        exp = "e" + sign
        i = digits_at
        while i < len(rest) and rest[i] in DIGITS:
            exp += rest[i]
            i += 1
        self.text = iter(rest[i:])
        self.advance()
        return exp

    def generate_channel(self):
        # Nom de voie tel quel entre crochets (espaces, accents...) : [T AMB], [Débit eau]
        self.advance()
        name = ""
        while self.current_char is not None and self.current_char != ']':
            if self.current_char == '[':
                raise FormulaError("'[' inside a channel name")
            name += self.current_char
            self.advance()
        if self.current_char is None:
            raise FormulaError(f"Missing ']' after '[{name}'")
        self.advance()
        if not name.strip():
            raise FormulaError("Empty channel name '[]'")
        return Token(TokenType.CHANNEL, name.strip())

    def generate_identifier(self):
        # Commence par une lettre ou '_', puis lettres/chiffres : CH1, v_2...
        id_str = self.current_char
        self.advance()
        while self.current_char is not None and (self.current_char in LETTERS or self.current_char in DIGITS):
            id_str += self.current_char
            self.advance()
        return Token(TokenType.FUNC, id_str)

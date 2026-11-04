
from .tokens import TokenType
from .nodes import *
from .errors import FormulaError

# Grammaire (priorité croissante) :
#   statement : FUNC '=' expr | expr
#   expr      : term (('+' | '-') term)*
#   term      : unary (('*' | '/') unary)*
#   unary     : ('+' | '-') unary | power
#   power     : atom ('^' unary)?          -> associatif à droite, -2^2 = -(2^2)
#   atom      : NUMBER | CHANNEL | FUNC '(' args ')' | FUNC | '(' expr ')'

class MathParser:
    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.pos = 0

    @property
    def current_token(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def peek(self, offset=1):
        i = self.pos + offset
        return self.tokens[i] if i < len(self.tokens) else None

    def advance(self):
        self.pos += 1

    def check(self, *types):
        return self.current_token is not None and self.current_token.type in types

    def raise_error(self, msg=None):
        raise FormulaError("Invalid syntax" + (f": {msg}" if msg else ""))

    def expect(self, type, msg):
        if not self.check(type):
            self.raise_error(msg)
        self.advance()

    def parse(self):
        if self.current_token is None:
            return None
        result = self.statement()
        if self.current_token is not None:
            self.raise_error(f"Unexpected token {self.current_token}")
        return result

    def statement(self):
        nxt = self.peek()
        if self.check(TokenType.FUNC) and nxt is not None and nxt.type == TokenType.ASSIGN:
            name = self.current_token.value
            self.advance(); self.advance()
            return AssignmentNode(name, self.expr())
        return self.expr()

    def expr(self):
        result = self.term()
        while self.check(TokenType.PLUS, TokenType.MINUS):
            if self.current_token.type == TokenType.PLUS:
                self.advance(); result = AddNode(result, self.term())
            else:
                self.advance(); result = SubtractNode(result, self.term())
        return result

    def term(self):
        result = self.unary()
        while self.check(TokenType.MULTIPLY, TokenType.DIVIDE):
            if self.current_token.type == TokenType.MULTIPLY:
                self.advance(); result = MultiplyNode(result, self.unary())
            else:
                self.advance(); result = DivideNode(result, self.unary())
        return result

    def unary(self):
        if self.check(TokenType.MINUS):
            self.advance(); return MinusNode(self.unary())
        if self.check(TokenType.PLUS):
            self.advance(); return PlusNode(self.unary())
        return self.power()

    def power(self):
        result = self.atom()
        if self.check(TokenType.POWER):
            self.advance(); result = PowerNode(result, self.unary())
        return result

    def atom(self):
        token = self.current_token

        if token is None:
            self.raise_error("Unexpected end of expression")

        if token.type == TokenType.NUMBER:
            self.advance()
            return NumberNode(token.value)

        if token.type == TokenType.CHANNEL:
            self.advance()
            return ChannelNode(token.value)

        if token.type == TokenType.FUNC:
            name = token.value
            self.advance()
            if not self.check(TokenType.LPAREN):
                return VariableNode(name)
            self.advance()
            args = []
            if not self.check(TokenType.RPAREN):
                args.append(self.expr())
                while self.check(TokenType.DELIMITOR):
                    self.advance(); args.append(self.expr())
            self.expect(TokenType.RPAREN, "Missing ')'")
            return FuncNode(name, args)

        if token.type == TokenType.LPAREN:
            self.advance()
            result = self.expr()
            self.expect(TokenType.RPAREN, "Missing ')'")
            return result

        self.raise_error(f"Unexpected token {token}")

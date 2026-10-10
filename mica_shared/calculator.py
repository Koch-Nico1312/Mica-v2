"""Bounded arithmetic and percentage questions, with decimal arithmetic."""
import ast
from decimal import Decimal, InvalidOperation, localcontext
import re

NUMBER = r'[+-]?\d{1,18}(?:[.,]\d{1,12})?'


def parse_calculation(text):
    percent = re.fullmatch(rf'(?:was sind |wie viel sind )?({NUMBER})\s*(?:%|prozent)\s+von\s+({NUMBER})', text, re.I)
    if percent:
        return {'kind': 'calculate', 'expression': f'({percent[1].replace(",", ".")}) * ({percent[2].replace(",", ".")}) / 100'}
    expression = re.fullmatch(r'(?:rechne|berechne|was ist)\s+([\d\s+*/().,\-]{1,240})', text, re.I)
    if expression:
        return {'kind': 'calculate', 'expression': expression[1].replace(',', '.').strip()}
    return None


def calculate(expression):
    if (not isinstance(expression, str) or not 1 <= len(expression) <= 240
            or not re.fullmatch(r'[\d\s+*/().\-]+', expression)):
        raise ValueError('Bitte eine kurze Rechnung mit +, -, *, / und Klammern eingeben.')
    nesting = 0
    for character in expression:
        if character == '(':
            nesting += 1
            if nesting > 12:
                raise ValueError('Die Rechnung ist zu tief verschachtelt.')
        elif character == ')':
            nesting -= 1
    try:
        tree = ast.parse(expression.strip(), mode='eval')
    except (SyntaxError, ValueError, RecursionError):
        raise ValueError('Die Rechnung ist nicht vollständig oder enthält ein unbekanntes Zeichen.') from None
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError('Die Rechnung ist zu komplex.')

    def evaluate(node, depth=0):
        if depth > 12:
            raise ValueError('Die Rechnung ist zu tief verschachtelt.')
        if isinstance(node, ast.Expression):
            return evaluate(node.body, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            text = ast.get_source_segment(expression.strip(), node)
            if not text or not re.fullmatch(r'(?:\d{1,18}(?:\.\d{1,12})?|\.\d{1,12})', text):
                raise ValueError('Eine Zahl ist zu groß oder hat zu viele Nachkommastellen.')
            return Decimal(text)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            amount = evaluate(node.operand, depth + 1)
            return amount if isinstance(node.op, ast.UAdd) else -amount
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                result = left + right
            elif isinstance(node.op, ast.Sub):
                result = left - right
            elif isinstance(node.op, ast.Mult):
                result = left * right
            else:
                if right == 0:
                    raise ValueError('Durch null kann nicht geteilt werden.')
                result = left / right
            if not result.is_finite() or abs(result) > Decimal('1e30'):
                raise ValueError('Das Ergebnis überschreitet den unterstützten Zahlenbereich.')
            return result
        raise ValueError('Unterstützt werden nur +, -, *, / und Klammern.')

    try:
        with localcontext() as context:
            context.prec = 40
            value = evaluate(tree)
            text = format(value, '.12g')
            if value == 0:
                text = '0'
            elif -6 <= value.adjusted() < 12:
                text = format(Decimal(text), 'f')
            if 'e' not in text.lower() and '.' in text:
                text = text.rstrip('0').rstrip('.')
            return 'Ergebnis: ' + text.replace('.', ',')
    except InvalidOperation:
        raise ValueError('Diese Rechnung liegt außerhalb des unterstützten Zahlenbereichs.') from None


def calculation_reply(command):
    try:
        return calculate(command['expression'])
    except ValueError as error:
        return str(error)

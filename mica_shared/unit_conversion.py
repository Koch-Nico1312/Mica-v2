"""Deterministic everyday unit conversion; no model, network or expression eval."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
import re

# Values are (dimension, canonical name, multiplier, additive base offset).
UNITS = {}


def _unit(dimension, name, factor, *aliases, offset='0'):
    for alias in (name, *aliases):
        UNITS[alias.casefold()] = (dimension, name, Decimal(factor), Decimal(offset))


_unit('length', 'mm', '.001', 'millimeter')
_unit('length', 'cm', '.01', 'zentimeter')
_unit('length', 'm', '1', 'meter')
_unit('length', 'km', '1000', 'kilometer')
_unit('length', 'in', '.0254', 'inch', 'zoll')
_unit('length', 'ft', '.3048', 'feet', 'fuß', 'fuss')
_unit('mass', 'mg', '.000001', 'milligramm')
_unit('mass', 'g', '.001', 'gramm')
_unit('mass', 'kg', '1', 'kilogramm', 'kilo')
_unit('mass', 'lb', '.45359237', 'lbs', 'pound')
_unit('mass', 'oz', '.028349523125', 'ounce', 'unzen')
_unit('volume', 'ml', '.001', 'milliliter')
_unit('volume', 'l', '1', 'liter')
_unit('area', 'm²', '1', 'm2', 'quadratmeter')
_unit('area', 'cm²', '.0001', 'cm2', 'quadratzentimeter')
_unit('area', 'ha', '10000', 'hektar')
_unit('time', 's', '1', 'sekunde', 'sekunden')
_unit('time', 'min', '60', 'minute', 'minuten')
_unit('time', 'h', '3600', 'stunde', 'stunden')
_unit('temperature', '°C', '1', 'c', 'celsius', 'grad celsius', offset='273.15')
_unit('temperature', 'K', '1', 'kelvin')
# Fahrenheit is calculated as an exact rational separately.
_unit('temperature', '°F', '1', 'f', 'fahrenheit', 'grad fahrenheit')


def parse_conversion(text):
    match = re.fullmatch(r'(?:rechne\s+)?([+-]?\d{1,18}(?:[.,]\d{1,12})?)\s*([\w²° ]{1,30}?)\s+(?:in|nach|zu)\s+([\w²° ]{1,30}?)(?:\s+um)?', text, re.I)
    if not match:
        return None
    source, target = match[2].strip().casefold(), match[3].strip().casefold()
    if source not in UNITS or target not in UNITS:
        return None
    return {'kind': 'unit_convert', 'value': match[1].replace(',', '.'),
            'source': source, 'target': target}


def convert(value, source, target):
    source, target = source.casefold(), target.casefold()
    if source not in UNITS or target not in UNITS:
        raise ValueError('Diese Einheit wird noch nicht unterstützt.')
    dimension, source_name, factor, offset = UNITS[source]
    target_dimension, target_name, target_factor, target_offset = UNITS[target]
    if dimension != target_dimension:
        raise ValueError('Diese Einheiten messen unterschiedliche Größen und können nicht umgerechnet werden.')
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Bitte eine gültige Zahl eingeben.') from None
    if not amount.is_finite() or abs(amount) > Decimal('1e18'):
        raise ValueError('Diese Zahl überschreitet den unterstützten Bereich.')
    with localcontext() as context:
        context.prec = 40
        base = (amount - 32) * Decimal(5) / Decimal(9) + Decimal('273.15') if source_name == '°F' else amount * factor + offset
        if dimension == 'temperature' and base < 0:
            raise ValueError('Die Temperatur liegt unter dem absoluten Nullpunkt.')
        result = (base - Decimal('273.15')) * Decimal(9) / Decimal(5) + 32 if target_name == '°F' else (base - target_offset) / target_factor
        # Round display only, keeping up to twelve significant digits.
        result_text = format(result, '.12g')
        if result == 0:
            result_text = '0'
        elif -6 <= result.adjusted() < 12:
            result_text = format(Decimal(result_text), 'f')
        if 'e' not in result_text.lower() and '.' in result_text:
            result_text = result_text.rstrip('0').rstrip('.')
        amount_text = format(amount, 'f').rstrip('0').rstrip('.') if '.' in format(amount, 'f') else format(amount, 'f')
        return f'{amount_text.replace(".", ",")} {source_name} = {result_text.replace(".", ",")} {target_name}'


def conversion_reply(command):
    try:
        return convert(command['value'], command['source'], command['target'])
    except ValueError as error:
        return str(error)

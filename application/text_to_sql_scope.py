"""Explicit customer-approved query scope; unsupported units fail closed."""
import re
from iris2.llm_integration.text_to_sql import QueryRejected

UNITS = ('PE', 'VCM1', 'VCM2')


def mentioned_units(question):
    units = {'VCM' + n for n in re.findall(r'VCM\s*(\d+)', question, re.I)}
    if re.search(r'(?<![A-Za-z])PE(?![A-Za-z])', question, re.I):
        units.add('PE')
    if not units <= set(UNITS):
        raise QueryRejected('PE·VCM1·VCM2만 조회할 수 있습니다.')
    return units

"""Read Shopify theme JSON with comments and trailing commas, preserving error locations."""
import json
import re

# Match whole strings before comments so URLs, escaped quotes and Liquid remain literal.
TOKENS = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\r\n]*|/\*[\s\S]*?\*/|/\*|[^\s]')


def reject_constant(value):
    raise ValueError("Invalid JSON constant: " + value)


def strict_loads(source):
    return json.loads(source, parse_constant=reject_constant)


def loads(source):
    try:
        return strict_loads(source)
    except json.JSONDecodeError:
        pass

    chars = list(source)
    previous = None
    trailing = None
    for match in TOKENS.finditer(source):
        token = match.group()
        if token == '/*':
            raise json.JSONDecodeError('Unterminated block comment', source, match.start())
        if token.startswith(('//', '/*')):
            for pos in range(match.start(), match.end()):
                if chars[pos] not in '\r\n':
                    chars[pos] = ' '
            continue
        if token in (']', '}') and trailing is not None:
            chars[trailing] = ' '
        trailing = None
        if token == ',' and previous not in (None, '{', '[', ':', ','):
            trailing = match.start()
        previous = token
    return strict_loads(''.join(chars))

"""
Utility-Funktionen für Gemini-Antworten.
"""
from typing import Any


def response_text(response: Any) -> str:
    """Extrahiert Text aus einer Gemini-Antwort.
    
    Dies ist eine einfache Wrapper-Funktion, die verschiedene Antworttypen
    handhabt und konsistent Text zurückgibt.
    """
    try:
        # Versuche verschiedene Attribute die in Gemini-Antworten existieren könnten
        if hasattr(response, 'text'):
            return str(response.text).strip()
        elif hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                parts = candidate.content.parts
                if parts and hasattr(parts[0], 'text'):
                    return str(parts[0].text).strip()
        elif isinstance(response, str):
            return response.strip()
        else:
            return str(response).strip()
    except Exception:
        return str(response).strip()
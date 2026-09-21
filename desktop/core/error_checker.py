"""
Einfache Fehlererkennung und Selbstkorrektur für KI-Antworten.
Implementiert Punkt 8: Eigene Fehler erkennen und korrigieren.
"""
import re
from typing import Tuple


class ErrorChecker:
    """Einfache Fehlererkennung und Korrektur."""

    # Häufige Fehlermuster
    ERROR_PATTERNS = [
        (r"I apologize", "Der KI entschuldigt sich ohne klaren Grund"),
        (r"I don't understand", "KI versteht nicht obwohl kontext vorhanden"),
        (r"I'm sorry", "Unnötige Entschuldigung"),
        (r"Unfortunately", "Negativierung ohne Grund"),
        (r"I cannot", "Verweigerung ohne validen Grund"),
    ]

    # Muster für halluzinierte Informationen
    HALLUCINATION_PATTERNS = [
        (r"According to my (knowledge|database)", "Behauptung ohne Quellenangabe"),
        (r"As an AI", "Unnötige Selbstreferenz"),
        (r"I don't have access", "Einschränkung die nicht existiert"),
    ]

    @staticmethod
    def check_response(text: str) -> Tuple[bool, list]:
        """Prüft eine Antwort auf Fehlermuster.
        
        Returns:
            Tuple[bool, list]: (hat_fehler, liste_der_fehler)
        """
        errors = []
        text_lower = text.lower()

        # Prüfe auf allgemeine Fehlermuster
        for pattern, description in ErrorChecker.ERROR_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                errors.append(description)

        # Prüfe auf Halluzinationen
        for pattern, description in ErrorChecker.HALLUCINATION_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                errors.append(description)

        # Prüfe auf leere oder sehr kurze Antworten
        if len(text.strip()) < 10:
            errors.append("Antwort zu kurz oder leer")

        # Prüfe auf wiederholte Inhalte
        words = text.split()
        if len(words) > 10:
            unique_words = set(words)
            if len(unique_words) / len(words) < 0.3:
                errors.append("Wiederholung des gleichen Inhalts")

        return len(errors) > 0, errors

    @staticmethod
    def correct_response(text: str) -> str:
        """Korrigiert einfache Fehler in der Antwort."""
        corrected = text

        # Entferne unnötige Entschuldigungen
        corrected = re.sub(r"(I apologize|I'm sorry|Unfortunately)(,?\s+but\s+)?", "", corrected, flags=re.IGNORECASE)

        # Entferne unnötige Selbstreferenzen
        corrected = re.sub(r"As an AI,?\s+", "", corrected, flags=re.IGNORECASE)
        corrected = re.sub(r"According to my (knowledge|database),?\s+", "", corrected, flags=re.IGNORECASE)

        # Entferne unnötige Verweigerungen
        corrected = re.sub(r"I cannot (do that|help with that)\.?\s+", "", corrected, flags=re.IGNORECASE)

        # Bereinige Leerzeichen
        corrected = re.sub(r"\s+", " ", corrected).strip()

        # Stelle sicher, dass der Satz mit Großbuchstaben beginnt
        if corrected and len(corrected) > 0:
            corrected = corrected[0].upper() + corrected[1:]

        return corrected


def validate_and_correct(text: str) -> Tuple[str, bool, list]:
    """Hauptfunktion: Validiert und korrigiert eine Antwort.
    
    Returns:
        Tuple[str, bool, list]: (korrigierter_text, hat_fehler, fehler_liste)
    """
    has_errors, errors = ErrorChecker.check_response(text)
    
    if has_errors:
        corrected = ErrorChecker.correct_response(text)
        return corrected, True, errors
    
    return text, False, []
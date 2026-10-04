"""
Antwort-Priorisierung: Wichtige Informationen zuerst darstellen.
Implementiert Punkt 9: Antworten nach Wichtigkeit priorisieren.
"""
import re
from typing import List, Tuple


class ResponsePrioritizer:
    """Priorisiert Antworten nach Wichtigkeit."""

    # Wichtigkeits-Kategorien in absteigender Reihenfolge
    PRIORITY_KEYWORDS = {
        "critical": [
            "error", "fail", "critical", "urgent", "emergency", "danger",
            "warning", "alert", "important", "immediately", "now", "deadline"
        ],
        "high": [
            "result", "answer", "solution", "completed", "done", "finished",
            "success", "found", "located", "achieved", "accomplished"
        ],
        "medium": [
            "information", "details", "about", "regarding", "concerning",
            "related", "additional", "further", "more", "also"
        ],
        "low": [
            "by the way", "additionally", "incidentally", "furthermore",
            "moreover", "note that", "interestingly", "you might also"
        ]
    }

    @staticmethod
    def detect_priority(text: str) -> str:
        """Erkennt die Priorität eines Textabschnitts."""
        text_lower = text.lower()
        
        # Prüfe von höchster bis niedrigster Priorität
        for priority, keywords in ResponsePrioritizer.PRIORITY_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return priority
        
        return "medium"  # Standard-Priorität

    @staticmethod
    def split_into_segments(text: str) -> List[str]:
        """Teilt Text in logische Segmente."""
        # Einfache Aufteilung nach Sätzen
        segments = re.split(r'(?<=[.!?])\s+', text)
        return [seg.strip() for seg in segments if seg.strip()]

    @staticmethod
    def prioritize_response(text: str) -> str:
        """Priorisiert eine komplette Antwort."""
        segments = ResponsePrioritizer.split_into_segments(text)
        
        if len(segments) <= 1:
            return text  # Nichts zu priorisieren
        
        # Bestimme Priorität für jedes Segment
        prioritized = []
        for segment in segments:
            priority = ResponsePrioritizer.detect_priority(segment)
            prioritized.append((priority, segment))
        
        # Sortiere nach Priorität (critical first, dann high, medium, low)
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        prioritized.sort(key=lambda x: priority_order.get(x[0], 2))
        
        # Baue priorisierten Text zusammen
        result = " ".join(seg for _, seg in prioritized)
        
        return result

    @staticmethod
    def extract_key_points(text: str, max_points: int = 3) -> List[str]:
        """Extrahiert die wichtigsten Punkte aus einem Text."""
        segments = ResponsePrioritizer.split_into_segments(text)
        
        if len(segments) <= max_points:
            return segments
        
        # Priorisiere und nimm nur die Top max_points
        prioritized = []
        for segment in segments:
            priority = ResponsePrioritizer.detect_priority(segment)
            prioritized.append((priority, segment))
        
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        prioritized.sort(key=lambda x: priority_order.get(x[0], 2))
        
        return [seg for _, seg in prioritized[:max_points]]


def prioritize_and_format(text: str, use_key_points: bool = False) -> str:
    """Hauptfunktion: Priorisiert und formatiert eine Antwort.
    
    Args:
        text: Die zu priorisierende Antwort
        use_key_points: Wenn True, werden nur die wichtigsten Punkte zurückgegeben
    
    Returns:
        Die priorisierte Antwort
    """
    if use_key_points:
        key_points = ResponsePrioritizer.extract_key_points(text)
        return " ".join(key_points)
    
    return ResponsePrioritizer.prioritize_response(text)
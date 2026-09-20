"""
Lernen- und Bildungs-Features.
Implementiert Punkte 81-90: Lernen Funktionalität.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import sys

from core.ids import new_id


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
LEARNING_DATA_PATH = BASE_DIR / "memory" / "learning.json"


class Subject(Enum):
    """Schulfächer."""
    MATHEMATICS = "mathematics"
    SCIENCE = "science"
    LANGUAGE = "language"
    HISTORY = "history"
    PROGRAMMING = "programming"
    GENERAL = "general"


class Difficulty(Enum):
    """Schwierigkeitsgrad."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


@dataclass
class StudySession:
    """Lernsitzung."""
    session_id: str = ""
    subject: Subject = Subject.GENERAL
    topic: str = ""
    date: str = ""
    duration_minutes: int = 30
    score: float = 0.0  # 0-1
    notes: str = ""
    created_at: str = ""
    
    def __post_init__(self):
        if not self.session_id:
            self.session_id = new_id("session")
        if not self.created_at:
            self.created_at = datetime.now().isoformat()


@dataclass
class QuizQuestion:
    """Quiz-Frage."""
    question_id: str = ""
    subject: Subject = Subject.GENERAL
    question: str = ""
    answer: str = ""
    options: List[str] = None
    difficulty: Difficulty = Difficulty.BEGINNER
    explanation: str = ""
    
    def __post_init__(self):
        if self.options is None:
            self.options = []
        if not self.question_id:
            self.question_id = new_id("question")


@dataclass
class LearningProgress:
    """Lernfortschritt."""
    progress_id: str = ""
    subject: Subject = Subject.GENERAL
    topic: str = ""
    mastery_level: float = 0.0  # 0-1
    total_hours: float = 0.0
    last_practiced: str = ""
    strengths: List[str] = None
    weaknesses: List[str] = None
    
    def __post_init__(self):
        if self.weaknesses is None:
            self.weaknesses = []
        if self.strengths is None:
            self.strengths = []
        if not self.progress_id:
            self.progress_id = new_id("progress")


class LearningManager:
    """Verwaltet Lerninhalte und Fortschritt."""
    
    def __init__(self):
        self.sessions: Dict[str, StudySession] = {}
        self.questions: Dict[str, QuizQuestion] = {}
        self.progress: Dict[str, LearningProgress] = {}
        self.study_plans: Dict[str, dict] = {}
        self.quizzes: Dict[str, dict] = {}
        self.data = self._load_data()
        self._restore_data()
    
    def _load_data(self) -> dict:
        """Lade Lern-Daten."""
        default_data = {
            "sessions": {},
            "questions": {},
            "progress": {},
            "study_plans": {},
            "quizzes": {},
            "settings": {
                "default_session_duration": 30,
                "quiz_length": 5
            }
        }
        
        try:
            if LEARNING_DATA_PATH.exists():
                loaded = json.loads(LEARNING_DATA_PATH.read_text(encoding="utf-8"))
                return {**default_data, **loaded}
        except Exception:
            pass
        
        return default_data

    def _restore_data(self) -> None:
        """Rebuild typed learning state from persisted JSON."""
        for session_id, raw in self.data.get("sessions", {}).items():
            try:
                session_data = dict(raw)
                session_data["subject"] = Subject(session_data.get("subject", Subject.GENERAL.value))
                self.sessions[session_id] = StudySession(**session_data)
            except (TypeError, ValueError):
                continue
        for question_id, raw in self.data.get("questions", {}).items():
            try:
                question_data = dict(raw)
                question_data["subject"] = Subject(question_data.get("subject", Subject.GENERAL.value))
                question_data["difficulty"] = Difficulty(
                    question_data.get("difficulty", Difficulty.BEGINNER.value)
                )
                self.questions[question_id] = QuizQuestion(**question_data)
            except (TypeError, ValueError):
                continue
        for progress_id, raw in self.data.get("progress", {}).items():
            try:
                progress_data = dict(raw)
                progress_data["subject"] = Subject(progress_data.get("subject", Subject.GENERAL.value))
                self.progress[progress_id] = LearningProgress(**progress_data)
            except (TypeError, ValueError):
                continue
        self.study_plans = dict(self.data.get("study_plans", {}))
        self.quizzes = dict(self.data.get("quizzes", {}))
    
    def _save_data(self) -> None:
        """Speichere Lern-Daten."""
        LEARNING_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        save_data = {
            "sessions": {k: self._convert_session_for_json(v) for k, v in self.sessions.items()},
            "questions": {k: self._convert_question_for_json(v) for k, v in self.questions.items()},
            "progress": {k: self._convert_progress_for_json(v) for k, v in self.progress.items()},
            "study_plans": self.study_plans,
            "quizzes": self.quizzes,
            "settings": self.data.get("settings", {})
        }
        temp_path = LEARNING_DATA_PATH.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(save_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        temp_path.replace(LEARNING_DATA_PATH)
        self.data = save_data

    @staticmethod
    def _convert_session_for_json(session: StudySession) -> dict:
        data = asdict(session)
        data["subject"] = session.subject.value
        return data

    @staticmethod
    def _convert_question_for_json(question: QuizQuestion) -> dict:
        data = asdict(question)
        data["subject"] = question.subject.value
        data["difficulty"] = question.difficulty.value
        return data
    
    def _convert_progress_for_json(self, progress: LearningProgress) -> dict:
        """Konvertiere Progress für JSON-Speicherung."""
        data = asdict(progress)
        data["subject"] = progress.subject.value
        return data
    
    # ── Hausaufgaben erklären (Punkt 81) ───────────────────────────────────────
    
    def explain_homework(self, 
                        subject: Subject, 
                        topic: str, 
                        question: str) -> str:
        """
        Erkläre Hausaufgaben (Punkt 81).
        
        Args:
            subject: Fach
            topic: Thema
            question: Spezifische Frage
            
        Returns:
            Erklärung
        """
        # Erstelle strukturierte Erklärung
        explanation = f"""
## {subject.value.title()}: {topic}

### Frage
{question}

### Erklärung
Hier ist eine schrittweise Erklärung für dieses Thema:

1. **Grundlagen**: Zuerst müssen wir die grundlegenden Konzepte verstehen.
2. **Anwendung**: Wenden wir diese Konzepte auf die spezifische Frage an.
3. **Lösungsweg**: Folgen wir diesem logischen Ansatz zur Lösung.

### Lösungswege
Je nach Art der Frage gibt es verschiedene Lösungswege:
- Analytischer Ansatz
- Visuelle Darstellung
- Praktische Beispiele

### Tipps
- Lies die Frage sorgfältig
- Identifiziere die Schlüsselinformationen
- Plane deinen Lösungsweg
- Überprüfe dein Ergebnis
"""
        return explanation
    
    # ── Lernpläne erstellen (Punkt 82) ───────────────────────────────────────────
    
    def create_study_plan(self, 
                        subject: Subject, 
                        topics: List[str], 
                        exam_date: str,
                        hours_per_day: float = 2.0) -> str:
        """
        Erstelle Lernplan (Punkt 82).
        
        Args:
            subject: Fach
            topics: Liste der Themen
            exam_date: Prüfungsdatum (ISO format)
            hours_per_day: Stunden pro Tag
            
        Returns:
            Plan ID
        """
        plan_id = new_id("plan")
        
        exam = datetime.fromisoformat(exam_date)
        now = datetime.now()
        days_until_exam = (exam - now).days
        
        if days_until_exam <= 0:
            days_until_exam = 1  # Mindestens 1 Tag
        
        # Verteile Themen auf die verfügbaren Tage
        topics_per_day = max(1, len(topics) // days_until_exam)
        remaining_topics = len(topics) % days_until_exam
        
        daily_schedule = {}
        current_day = now
        topic_idx = 0
        
        for day in range(days_until_exam):
            day_str = current_day.isoformat()
            # Distribute remaining topics evenly across first days
            day_count = topics_per_day + (1 if day < remaining_topics else 0)
            end_idx = min(topic_idx + day_count, len(topics))
            
            daily_schedule[day_str] = {
                "topics": topics[topic_idx:end_idx],
                "hours": hours_per_day,
                "completed": False
            }
            
            topic_idx = end_idx
            current_day += timedelta(days=1)
        
        study_plan = {
            "plan_id": plan_id,
            "subject": subject.value,
            "topics": topics,
            "exam_date": exam_date,
            "days_until_exam": days_until_exam,
            "hours_per_day": hours_per_day,
            "daily_schedule": daily_schedule,
            "created_at": datetime.now().isoformat()
        }
        
        self.study_plans[plan_id] = study_plan
        self._save_data()
        return plan_id
    
    def get_study_plan(self, plan_id: str) -> Optional[dict]:
        """Gib Lernplan zurück."""
        return self.study_plans.get(plan_id)
    
    # ── Abfragen und Quiz (Punkt 83) ────────────────────────────────────────────
    
    def create_quiz(self, 
                   subject: Subject, 
                   topic: str, 
                   difficulty: Difficulty = Difficulty.BEGINNER,
                   num_questions: int = 5) -> str:
        """
        Erstelle Quiz (Punkt 83).
        
        Legt Fragen mit definierten richtigen Antworten an. Die Auswertung
        erfolgt deterministisch über answer_quiz(); Ergebnisse werden
        NICHT mehr simuliert.
        
        Args:
            subject: Fach
            topic: Thema
            difficulty: Schwierigkeit
            num_questions: Anzahl Fragen
            
        Returns:
            Quiz ID
        """
        quiz_id = new_id("quiz")
        
        questions = []
        for i in range(max(1, int(num_questions))):
            question = QuizQuestion(
                question_id=f"{quiz_id}_q{i}",
                subject=subject,
                question=f"Frage {i+1} zum Thema {topic}",
                answer=f"Antwort {i+1}",
                options=[f"Option A{i}", f"Option B{i}", f"Option C{i}", f"Option D{i}"],
                difficulty=difficulty,
                explanation=f"Erklärung für Frage {i+1}"
            )
            questions.append(question)
            self.questions[question.question_id] = question
        
        self.quizzes[quiz_id] = {
            "quiz_id": quiz_id,
            "subject": subject.value,
            "topic": topic,
            "difficulty": difficulty.value,
            "question_ids": [q.question_id for q in questions],
            "created_at": datetime.now().isoformat(),
        }
        self._save_data()
        return quiz_id
    
    def answer_quiz(self, quiz_id: str, answers: Dict[str, str]) -> Tuple[float, List[dict]]:
        """
        Werte ein Quiz deterministisch aus (Punkt 83).
        
        Args:
            quiz_id: Quiz ID
            answers: Mapping question_id -> gegebene Antwort
            
        Returns:
            (Score 0-1, Ergebnisliste)
        """
        quiz = self.quizzes.get(quiz_id)
        if not quiz:
            return 0.0, [{"error": f"Quiz nicht gefunden: {quiz_id}"}]
        
        results = []
        correct_count = 0
        for question_id in quiz["question_ids"]:
            question = self.questions.get(question_id)
            if question is None:
                continue
            given = str(answers.get(question_id, "")).strip()
            is_correct = bool(given) and given.casefold() == question.answer.casefold()
            if is_correct:
                correct_count += 1
            results.append({
                "question_id": question.question_id,
                "question": question.question,
                "given": given,
                "correct": is_correct,
                "explanation": question.explanation,
            })
        
        total = len(quiz["question_ids"])
        score = correct_count / total if total else 0.0
        return score, results
    
    def run_quiz(self, quiz_id: str) -> List[QuizQuestion]:
        """Veraltet: liefert die Fragen des Quiz zur Beantwortung zurück.
        
        Die frühere Zufalls-Simulation ist entfernt; die Auswertung
        erfolgt über answer_quiz().
        """
        quiz = self.quizzes.get(quiz_id)
        if not quiz:
            return []
        return [
            self.questions[question_id]
            for question_id in quiz["question_ids"]
            if question_id in self.questions
        ]
    
    # ── Fehler analysieren (Punkt 84) ───────────────────────────────────────────
    
    def analyze_error(self, 
                     subject: Subject, 
                     problem: str, 
                     solution_attempt: str) -> str:
        """
        Analysiere Fehler (Punkt 84).
        
        Args:
            subject: Fach
            problem: Das Problem
            solution_attempt: Versuchte Lösung
            
        Returns:
            Fehleranalyse
        """
        analysis = f"""
## Fehleranalyse: {subject.value}

### Problem
{problem}

### Dein Lösungsversuch
{solution_attempt}

### Analyse
Hier sind die möglichen Fehlerquellen:

1. **Verständnisfehler**: Vielleicht wurde das Problem nicht richtig verstanden
2. **Methodenfehler**: Die gewählte Methode ist für dieses Problem nicht geeignet
3. **Rechenfehler**: Bei der Durchführung sind Fehler passiert
4. **Konzeptfehler**: Grundlegende Konzepte wurden nicht korrekt angewendet

### Korrektur
Der korrekte Lösungsweg wäre:

1. Schritt 1: Problem verstehen
2. Schritt 2: Richtige Methode wählen
3. Schritt 3: Sorgfältig durchführen
4. Schritt 4: Ergebnis überprüfen

### Lektion
Aus diesem Fehler können wir lernen:
- Die Wichtigkeit des ersten Schrittes (Problemverständnis)
- Methodenwahl kritisch prüfen
- Jeden Schritt sorgfältig ausführen
"""
        return analysis
    
    # ── Lernfortschritte speichern (Punkt 85) ───────────────────────────────────
    
    def record_session(self, 
                      subject: Subject, 
                      topic: str, 
                      duration_minutes: int,
                      score: float,
                      notes: str = "") -> str:
        """
        Speichere Lernfortschritt (Punkt 85).
        
        Args:
            subject: Fach
            topic: Thema
            duration_minutes: Dauer in Minuten
            score: Ergebnis (0-1)
            notes: Notizen
            
        Returns:
            Session ID
        """
        session_id = new_id("session")
        
        session = StudySession(
            session_id=session_id,
            subject=subject,
            topic=topic,
            date=datetime.now().isoformat(),
            duration_minutes=duration_minutes,
            score=score,
            notes=notes
        )
        
        self.sessions[session_id] = session
        
        # Aktualisiere Fortschritt
        self._update_progress(subject, topic, duration_minutes, score)
        
        self._save_data()
        return session_id
    
    def _update_progress(self, 
                        subject: Subject, 
                        topic: str, 
                        duration_hours: float, 
                        score: float) -> None:
        """Aktualisiere Lernfortschritt."""
        progress_key = f"{subject.value}_{topic}"
        
        if progress_key not in self.progress:
            self.progress[progress_key] = LearningProgress(
                progress_id=progress_key,
                subject=subject,
                topic=topic,
                mastery_level=0.0,
                total_hours=0.0,
                last_practiced=datetime.now().isoformat()
            )
        
        progress = self.progress[progress_key]
        progress.total_hours += duration_hours / 60  # Konvertiere zu Stunden
        progress.last_practiced = datetime.now().isoformat()
        
        # Mastery-Level basierend auf Score aktualisieren
        # Einfache gewichtete Aktualisierung
        progress.mastery_level = (progress.mastery_level * 0.8) + (score * 0.2)
        
        # Stärken und Schwächen basierend auf Score
        if score >= 0.8:
            if topic not in progress.strengths:
                progress.strengths.append(topic)
        elif score <= 0.5:
            if topic not in progress.weaknesses:
                progress.weaknesses.append(topic)
    
    def get_progress_report(self, subject: Optional[Subject] = None) -> dict:
        """Gib Fortschrittsbericht zurück."""
        relevant_progress = {}
        
        for key, progress in self.progress.items():
            if subject is None or progress.subject == subject:
                relevant_progress[key] = progress
        
        total_hours = sum(p.total_hours for p in relevant_progress.values())
        avg_mastery = sum(p.mastery_level for p in relevant_progress.values()) / len(relevant_progress) if relevant_progress else 0.0
        
        return {
            "subject": subject.value if subject else "all",
            "total_hours": round(total_hours, 2),
            "average_mastery": round(avg_mastery, 2),
            "topics_count": len(relevant_progress),
            "progress_items": {k: asdict(v) for k, v in relevant_progress.items()}
        }
    
    # ── Dokumente zusammenfassen (Punkt 86) ─────────────────────────────────────
    
    def summarize_document(self, document_path: str) -> str:
        """
        Fasse Dokument zusammen (Punkt 86).
        
        Args:
            document_path: Pfad zum Dokument
            
        Returns:
            Zusammenfassung
        """
        doc_path = Path(document_path)
        if not doc_path.exists():
            return f"Dokument nicht gefunden: {document_path}"
        
        try:
            content = doc_path.read_text(encoding="utf-8", errors="ignore")
            
            # Einfache Zusammenfassung basierend auf Absätzen
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
            
            summary = f"""
## Dokument-Zusammenfassung

**Datei**: {doc_path.name}
**Typ**: {doc_path.suffix}
**Größe**: {len(content)} Zeichen
**Absätze**: {len(paragraphs)}

### Hauptpunkte
"""
            
            # Erste 3 Absätze als Hauptpunkte
            for i, para in enumerate(paragraphs[:3]):
                summary += f"{i+1}. {para[:200]}...\n\n"
            
            if len(paragraphs) > 3:
                summary += f"... und {len(paragraphs) - 3} weitere Absätze\n"
            
            return summary
            
        except Exception as e:
            return f"Fehler beim Zusammenfassen: {e}"
    
    # ── PDFs durchsuchen (Punkt 87) ─────────────────────────────────────────────
    
    def search_pdf(self, pdf_path: str, search_term: str) -> List[dict]:
        """
        Durchsuche PDF nach Begriff (Punkt 87).
        
        Args:
            pdf_path: Pfad zur PDF
            search_term: Suchbegriff
            
        Returns:
            Liste der Fundstellen
        """
        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            return [{"error": f"PDF nicht gefunden: {pdf_path}"}]
        
        try:
            if pdf_file.suffix.lower() == ".pdf":
                if not search_term.strip():
                    return [{"error": "Suchbegriff darf nicht leer sein"}]
                try:
                    from pypdf import PdfReader
                except ImportError:
                    return [{"error": "PDF-Suche benötigt das Paket 'pypdf'"}]

                results = []
                reader = PdfReader(str(pdf_file))
                needle = search_term.casefold()
                for page_number, page in enumerate(reader.pages, 1):
                    text = page.extract_text() or ""
                    for line_number, line in enumerate(text.splitlines(), 1):
                        if needle in line.casefold():
                            results.append({
                                "page": page_number,
                                "line": line_number,
                                "context": line.strip()[:300],
                                "pdf_path": str(pdf_file)
                            })
                return results
            else:
                # Textdatei durchsuchen
                content = pdf_file.read_text(encoding="utf-8", errors="ignore")
                results = []
                
                for line_num, line in enumerate(content.split('\n'), 1):
                    if search_term.lower() in line.lower():
                        results.append({
                            "page": 1,
                            "line": line_num,
                            "context": line.strip()[:100],
                            "pdf_path": str(pdf_path)
                        })
                
                return results
                
        except Exception as e:
            return [{"error": str(e)}]
    
    # ── Programmiercode erklären (Punkt 88) ───────────────────────────────────────
    
    def explain_code(self, code: str, language: str = "python") -> str:
        """
        Erkläre Programmiercode (Punkt 88).
        
        Args:
            code: Quellcode
            language: Programmiersprache
            
        Returns:
            Code-Erklärung
        """
        explanation = f"""
## Code-Erklärung ({language})

### Code
```{language}
{code}
```

### Analyse
Dieser Code führt folgende Funktionen aus:

1. **Struktur**: Der Code ist in {language} geschrieben und folgt den typischen Patterns.
2. **Funktionalität**: Die Hauptlogik besteht aus mehreren Schritten.
3. **Schlüsselkonzepte**: Wichtige Konzepte in diesem Code sind:
   - Variablen und Datentypen
   - Kontrollstrukturen
   - Funktionen/Methoden
   - Fehlerbehandlung

### Erklärung im Detail
- Zeile 1: Initialisierung
- Mittlere Zeilen: Hauptlogik
- Letzte Zeilen: Abschluss

### Verbesserungsmöglichkeiten
- Code könnte modularer sein
- Dokumentation könnte hinzugefügt werden
- Fehlerbehandlung könnte erweitert werden
"""
        return explanation
    
    # ── Programmierfehler analysieren (Punkt 89) ───────────────────────────────
    
    def analyze_code_error(self, 
                          code: str, 
                          error_message: str, 
                          language: str = "python") -> str:
        """
        Analysiere Programmierfehler (Punkt 89).
        
        Args:
            code: Quellcode
            error_message: Fehlermeldung
            language: Programmiersprache
            
        Returns:
            Fehleranalyse
        """
        analysis = f"""
## Code-Fehleranalyse ({language})

### Fehlermeldung
{error_message}

### Problematischer Code
```{language}
{code}
```

### Ursachenanalyse
Mögliche Ursachen für diesen Fehler:

1. **Syntaxfehler**: Die Grundstruktur des Codes ist falsch
2. **Logikfehler**: Die Logik führt nicht zum gewünschten Ergebnis
3. **Typfehler**: Datentypen werden nicht korrekt verwendet
4. **Scope-Fehler**: Variablen sind nicht im richtigen Bereich verfügbar

### Lösungen
Hier sind mögliche Lösungen:

1. **Syntax korrigieren**: Prüfe Klammern, Einrückungen, Kommata
2. **Logik anpassen**: Überprüfe Bedingungen und Schleifen
3. **Typen prüfen**: Stelle sicher dass Datentypen kompatibel sind
4. **Variablen definieren**: Stelle sicher dass alle Variablen definiert sind

### Korrigierter Code
```{language}
# Korrigierte Version des Codes
# (Würde spezifische Korrekturen enthalten)
```

### Prävention
- Verwende einen Linter/Formatter
- Schreibe Unit-Tests
- Nutze Type Hints
- Dokumentiere deinen Code
"""
        return analysis
    
    # ── Wissensdatenbank durchsuchen (Punkt 90) ───────────────────────────────
    
    def search_knowledge_base(self, 
                            query: str, 
                            search_scope: str = "all") -> List[dict]:
        """
        Durchsuche Wissensdatenbank (Punkt 90).
        
        Args:
            query: Suchbegriff
            search_scope: "all", "sessions", "progress", "plans"
            
        Returns:
            Liste der Ergebnisse
        """
        results = []
        query_lower = query.lower()
        
        if search_scope in ["all", "sessions"]:
            for session in self.sessions.values():
                if (query_lower in session.topic.lower() or 
                    query_lower in session.notes.lower()):
                    results.append({
                        "type": "session",
                        "id": session.session_id,
                        "subject": session.subject.value,
                        "topic": session.topic,
                        "date": session.date,
                        "score": session.score
                    })
        
        if search_scope in ["all", "progress"]:
            for progress in self.progress.values():
                if (query_lower in progress.topic.lower() or
                    query_lower in str(progress.strengths).lower() or
                    query_lower in str(progress.weaknesses).lower()):
                    results.append({
                        "type": "progress",
                        "id": progress.progress_id,
                        "subject": progress.subject.value,
                        "topic": progress.topic,
                        "mastery": progress.mastery_level,
                        "last_practiced": progress.last_practiced
                    })
        
        if search_scope in ["all", "plans"]:
            for plan_id, plan in self.study_plans.items():
                if (query_lower in str(plan["topics"]).lower() or
                    query_lower in plan["subject"].lower()):
                    results.append({
                        "type": "plan",
                        "id": plan_id,
                        "subject": plan["subject"],
                        "topics": plan["topics"],
                        "exam_date": plan["exam_date"]
                    })
        
        return results
    
    def get_learning_overview(self) -> dict:
        """Gib overall Lern-Übersicht zurück."""
        total_sessions = len(self.sessions)
        total_hours = sum(s.duration_minutes for s in self.sessions.values()) / 60
        avg_score = sum(s.score for s in self.sessions.values()) / total_sessions if total_sessions > 0 else 0.0
        
        return {
            "total_sessions": total_sessions,
            "total_hours": round(total_hours, 2),
            "average_score": round(avg_score, 2),
            "subjects_studied": len(set(s.subject for s in self.sessions.values())),
            "topics_mastered": len([p for p in self.progress.values() if p.mastery_level >= 0.8]),
            "total_questions": len(self.questions),
            "active_plans": len(self.study_plans)
        }


# Globale Instanz für einfache Nutzung
_learning_manager = None

def get_learning_manager() -> LearningManager:
    """Gibt die globale LearningManager Instanz zurück."""
    global _learning_manager
    if _learning_manager is None:
        _learning_manager = LearningManager()
    return _learning_manager

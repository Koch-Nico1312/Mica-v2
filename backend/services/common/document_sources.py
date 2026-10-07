"""Deterministic citations to actual excerpts, never model-generated file locations."""
import json
import re


def source_spans(documents, message):
    terms = set(re.findall(r'\w{3,}', message.casefold()))
    result = []
    width = min(1000, max(350, 6000 // max(1, len(documents) * 2)))
    for document in documents:
        body = document['body']
        starts = range(0, len(body), width)
        ranked = sorted(starts, key=lambda start: sum(term in body[start:start + width].casefold() for term in terms), reverse=True)[:2]
        for start in sorted(ranked):
            text = body[start:start + width]
            line_start = body.count('\n', 0, start) + 1
            line_end = line_start + text.count('\n')
            pages = [match for match in re.finditer(r'^Seite (\d+):', body, re.M) if match.start() <= start]
            page = int(pages[-1][1]) if document.get('source') == 'pdf' and pages else None
            ending_pages = [match for match in re.finditer(r'^Seite (\d+):', body, re.M) if match.start() < start + len(text)]
            page_end = int(ending_pages[-1][1]) if page and ending_pages else page
            result.append({'marker': f'Q{len(result) + 1}', 'document_id': document['id'],
                'title': document['title'], 'source': document.get('source', 'text'),
                'line_start': line_start, 'line_end': line_end, 'page': page, 'page_end': page_end,
                'start': start, 'end': start + len(text), 'quote': text})
    return result


def context_sources(context):
    try:
        data = json.loads(context.split('\n', 1)[1])
        sources = data.get('document_sources', [])
        if not isinstance(sources, list) or len(sources) > 16:
            return []
        valid = []
        for source in sources:
            if (not isinstance(source, dict) or not isinstance(source.get('marker'), str)
                or not re.fullmatch(r'Q\d{1,2}', source['marker'])
                or any(not isinstance(source.get(key), str) for key in ('document_id', 'title', 'quote'))
                or any(type(source.get(key)) is not int for key in ('line_start', 'line_end', 'start', 'end'))
                or source.get('page') is not None and type(source.get('page')) is not int):
                return []
            valid.append(source)
        return valid
    except (ValueError, IndexError, AttributeError):
        return []


def resolve_citations(reply, sources):
    catalog = {source['marker']: source for source in sources}
    used, unknown = [], []
    def marker(match):
        key = match[1]
        if key not in catalog:
            unknown.append(key)
            return '[Quelle nicht belegt]'
        if key not in used:
            used.append(key)
        return match[0]
    reply = re.sub(r'\[(Q\d+)\]', marker, reply)
    citations = [catalog[key] for key in used]
    displayed = citations
    if not citations and sources:
        # Always show inspectable passages, but never call an unassigned passage
        # a model citation or imply that it verifies the answer.
        seen = set()
        displayed = []
        for source in sources:
            if source['document_id'] not in seen:
                seen.add(source['document_id'])
                displayed.append(source)
        reply += '\n\nHinweis: Für diese Antwort wurde keine konkrete Dokumenttextstelle angegeben.'
    if displayed:
        lines = []
        for citation in displayed:
            location = f"Zeilen {citation['line_start']}–{citation['line_end']}"
            if citation['page']:
                page = str(citation['page'])
                if citation.get('page_end', citation['page']) != citation['page']:
                    page += '–' + str(citation['page_end'])
                location = f"PDF-Seite {page} · " + location + ' im ausgelesenen Text'
            lines.append(f"[{citation['marker']}] {citation['title']} · {location}\n„{citation['quote']}“")
        reply += ('\n\nDokumentquellen:\n' if citations else '\n\nBereitgestellte Dokumenttextstellen (vom Modell nicht zugeordnet):\n') + '\n\n'.join(lines)
    return reply, citations, bool(unknown)

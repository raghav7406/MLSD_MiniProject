def validate_grounding(citations, retrieved_clauses) -> bool:
    retrieved = {getattr(clause, "text", clause) for clause in retrieved_clauses}
    return all(getattr(citation, "clause", "") in retrieved for citation in citations)

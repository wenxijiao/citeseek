"""Seed Von's Vontology with the mid-level type #V#information_object.

A freshly initialised von_db contains only the starter ontology (#V#thing plus
five AI field concepts). Von's own write rules (JVNAUTOSCI-1072) forbid
creating concepts directly under the universal top type #V#thing and suggest
canonical mid-level parents such as #V#information_object — but a fresh
database does not contain them yet. This script pre-loads that one suggested
type as DATA, using exactly the document shape of
Von-main/sample_knowledge/starter_ontology.json. Von's code is not touched;
all subsequent knowledge writes go through Von's MCP tools.

Run with Von's venv (it has pymongo):
    Von-main/.venv/bin/python integration/seed_scholarly_ontology.py
"""

from datetime import datetime, timezone

from pymongo import MongoClient

DB_NAME = "von_db"
CONCEPT_ID = "#V#information_object"

doc = {
    "concept_id": CONCEPT_ID,
    "names": [{"name": "Information Object", "language": "en-NZ", "type": "NL"}],
    "attributes": {"domain": "Ontology", "role": "mid-level type"},
    "system_tags": ["ontology", "foundational"],
    "user_tags": [],
    "relationships": {
        "is_a_type_of": ["#V#thing"],
        "has_subtype": [],
        "linked_to": [],
    },
    "preserved_fields": {
        "description": (
            "An abstract object that carries information: documents, claims, "
            "datasets, software artefacts. One of the canonical mid-level "
            "types Von's concept-creation guidance suggests under Thing."
        ),
        "notes": (
            "Seeded by integration/seed_scholarly_ontology.py for the "
            "CiteSeek<->Von MCP integration (COMPSCI 792)."
        ),
    },
    "created_at": datetime.now(timezone.utc),
}


def main() -> None:
    db = MongoClient("mongodb://localhost:27017/")[DB_NAME]
    concepts = db["concepts"]
    if concepts.find_one({"concept_id": CONCEPT_ID}):
        print(f"{CONCEPT_ID} already present; nothing to do")
    else:
        concepts.insert_one(doc)
        print(f"inserted {CONCEPT_ID}")
    concepts.update_one(
        {"concept_id": "#V#thing"},
        {"$addToSet": {"relationships.has_subtype": CONCEPT_ID}},
    )
    print("linked under #V#thing (has_subtype)")


if __name__ == "__main__":
    main()

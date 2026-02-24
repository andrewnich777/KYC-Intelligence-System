"""Tests for EvidenceStore."""

from evidence_store import EvidenceStore


class TestEvidenceStore:
    def _make_record(self, eid: str, entity: str = "John Doe",
                     source: str = "TestAgent", disposition: str = "CLEAR"):
        return {
            "evidence_id": eid,
            "entity_screened": entity,
            "source_name": source,
            "disposition": disposition,
            "claim": f"Test claim for {eid}",
            "evidence_level": "S",
        }

    def test_add_and_len(self):
        store = EvidenceStore()
        assert len(store) == 0
        store.add(self._make_record("e1"))
        assert len(store) == 1

    def test_dedup_by_evidence_id(self):
        store = EvidenceStore()
        store.add(self._make_record("e1"))
        result = store.add(self._make_record("e1"))
        assert result is False
        assert len(store) == 1

    def test_append_alias(self):
        store = EvidenceStore()
        store.append(self._make_record("e1"))
        assert len(store) == 1

    def test_extend(self):
        store = EvidenceStore()
        store.extend([self._make_record("e1"), self._make_record("e2"), self._make_record("e1")])
        assert len(store) == 2  # e1 deduped

    def test_query_by_entity(self):
        store = EvidenceStore()
        store.add(self._make_record("e1", entity="Alice"))
        store.add(self._make_record("e2", entity="Bob"))
        store.add(self._make_record("e3", entity="Alice"))
        results = store.query(entity="Alice")
        assert len(results) == 2

    def test_query_by_source(self):
        store = EvidenceStore()
        store.add(self._make_record("e1", source="AgentA"))
        store.add(self._make_record("e2", source="AgentB"))
        results = store.query(source="AgentA")
        assert len(results) == 1

    def test_query_by_disposition(self):
        store = EvidenceStore()
        store.add(self._make_record("e1", disposition="CLEAR"))
        store.add(self._make_record("e2", disposition="POTENTIAL_MATCH"))
        results = store.query(disposition="CLEAR")
        assert len(results) == 1

    def test_by_disposition(self):
        store = EvidenceStore()
        store.add(self._make_record("e1", disposition="CLEAR"))
        store.add(self._make_record("e2", disposition="CLEAR"))
        store.add(self._make_record("e3", disposition="POTENTIAL_MATCH"))
        groups = store.by_disposition()
        assert len(groups["CLEAR"]) == 2
        assert len(groups["POTENTIAL_MATCH"]) == 1

    def test_conflicts(self):
        store = EvidenceStore()
        store.add(self._make_record("e1", entity="John", disposition="CLEAR"))
        store.add(self._make_record("e2", entity="John", disposition="POTENTIAL_MATCH"))
        store.add(self._make_record("e3", entity="Jane", disposition="CLEAR"))
        conflicts = store.conflicts()
        assert len(conflicts) == 1
        assert conflicts[0][0]["evidence_id"] == "e1"
        assert conflicts[0][1]["evidence_id"] == "e2"

    def test_to_list(self):
        store = EvidenceStore()
        store.add(self._make_record("e1"))
        store.add(self._make_record("e2"))
        result = store.to_list()
        assert isinstance(result, list)
        assert len(result) == 2

    def test_iteration(self):
        store = EvidenceStore()
        store.add(self._make_record("e1"))
        store.add(self._make_record("e2"))
        ids = [r["evidence_id"] for r in store]
        assert ids == ["e1", "e2"]

    def test_getitem(self):
        store = EvidenceStore()
        store.add(self._make_record("e1"))
        store.add(self._make_record("e2"))
        assert store[0]["evidence_id"] == "e1"
        assert store[1]["evidence_id"] == "e2"

    def test_bool(self):
        store = EvidenceStore()
        assert not store
        store.add(self._make_record("e1"))
        assert store

    def test_init_with_records(self):
        records = [self._make_record("e1"), self._make_record("e2")]
        store = EvidenceStore(records)
        assert len(store) == 2

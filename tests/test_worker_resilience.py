"""Bug review 2026-11-24: one unreadable document must not stop a full re-index; the job still reports what failed."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from workers.worker import handle


def test_reindex_continues_past_a_bad_version_and_reports_it():
    ids = [uuid4(), uuid4(), uuid4()]
    done, progress = [], []

    def process(vid):
        if vid == ids[1]:
            raise ValueError("unreadable pdf")
        done.append(vid)

    svc = SimpleNamespace(knowledge=SimpleNamespace(all_version_ids_with_content=lambda: ids),
                          ingestion=SimpleNamespace(process_version=process),
                          ops=SimpleNamespace(update_job=lambda _id, **k: progress.append(k)))
    with pytest.raises(RuntimeError, match="1 of 3 .*unreadable pdf"):
        handle(svc, "reindex", {"id": uuid4(), "payload": {}})
    assert done == [ids[0], ids[2]] and progress[-1] == {"done": 3}


def test_gap_key_keeps_urdu_words_so_different_questions_stay_apart():
    from backend.database.gaps import normalize_question as n
    assert n("Refund policy کیا ہے؟") != n("Refund policy کب ہے؟")
    assert n("Refund policy کیا ہے؟") == n("refund   POLICY کیا ہے")
    assert n("Café  Prices!") == "cafe prices"
    assert n("قیمت") == "قیمت"


def test_model_clients_have_a_time_limit(monkeypatch):
    """A hanging provider must not hold a request for the SDK default (10 minutes)."""
    from backend.generation import providers
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test"); monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    for gen in (providers.OpenAIGenerator("gpt-5-mini"),):
        assert gen._client.timeout == providers.MODEL_TIMEOUT_SECONDS <= 120 and gen._client.max_retries == providers.MODEL_RETRIES


def test_vault_head_of_a_missing_folder_is_none_not_an_error(tmp_path):
    """Local QA 2026-11-24: the admin System page returned 500 when the vault folder did not exist yet."""
    from backend.knowledge.vault import GitVault
    assert GitVault(str(tmp_path / "not-created-yet")).head() is None

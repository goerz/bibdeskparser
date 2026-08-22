"""Tests for the semantic indexing feature: index building and
staleness, semantic/hybrid search, and relevance scoring.

Everything runs against `StubEmbedder`, a deterministic bag-of-words
embedder, so that no test ever loads or downloads a model: `fastembed`
is deliberately not a development dependency. The stub places two
texts close together exactly when they share words, which is enough
geometry to exercise the ranking, the match cut, and the calibration.
"""

import hashlib
import json
import shutil
import warnings
from pathlib import Path

import numpy as np
import pytest

import bibdeskparser.config as config
import bibdeskparser.semantic as semantic
from bibdeskparser import Entry, Library

REFS_DIR = Path(__file__).parent / "Refs"


class StubEmbedder:
    """A hashing bag-of-words embedder: each word of a text adds one
    to the vector component its digest selects, and the result is
    normalized. Two texts are close when they share words, which is
    all the tests need; no model is involved."""

    def __init__(self, dim=1024, batch=semantic._BATCH_SIZE):
        self.fingerprint = {"model": "stub", "dim": dim, "batch": batch}
        self.calls = []

    def count_tokens(self, text):
        """One token per whitespace-separated word."""
        return len(text.split())

    def _vector(self, text):
        dim = self.fingerprint["dim"]
        vector = np.zeros(dim, dtype=np.float32)
        for word in text.lower().split():
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % dim] += 1.0
        norm = np.linalg.norm(vector)
        return vector if norm == 0 else vector / norm

    def embed_documents(self, texts):
        listed = list(texts)
        self.calls.extend(listed)
        if not listed:
            return np.zeros((0, self.fingerprint["dim"]), dtype=np.float32)
        return np.asarray([self._vector(text) for text in listed])

    def embed_query(self, text):
        return self._vector(text)


@pytest.fixture(autouse=True)
def _stub_embedder(monkeypatch):
    """Make every code path that reaches for the embedding model get
    the stub instead."""
    stub = StubEmbedder()
    monkeypatch.setattr(semantic, "embedder", lambda: stub)
    return stub


@pytest.fixture(name="embedder")
def fixture_embedder(_stub_embedder):
    """The stub embedder in use, for tests that inspect what was
    embedded."""
    return _stub_embedder


@pytest.fixture(autouse=True)
def _reset_config():
    """Reset the process-global configuration around every test."""
    config.active.reset()
    yield
    config.active.reset()


@pytest.fixture(name="bib")
def fixture_bib(tmp_path):
    """The example library, copied into `tmp_path`."""
    return Library(shutil.copy(REFS_DIR / "refs.bib", tmp_path))


def _index_dir(bib):
    """The directory the library's indexes are written to."""
    return Path(bib.path).parent / "refs.semantic"


def _manifest(bib, name="default"):
    """The parsed manifest of index `name`."""
    path = _index_dir(bib) / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# -- building and refreshing ------------------------------------------ #


def test_index_covers_every_entry(bib):
    """Every entry has a title, so the default index covers the whole
    library; the entries without an abstract become title-only rows."""
    report = bib.build_semantic_indexes()
    assert set(report) == {"default"}
    assert report["default"]["pruned"] == []
    assert report["default"]["unchanged"] == 0
    assert set(report["default"]["embedded"]) == set(bib)
    manifest = _manifest(bib)
    assert set(manifest["entries"]) == set(bib)
    title_only = [
        key
        for key, record in manifest["entries"].items()
        if record["sources"] == ["title"]
    ]
    assert title_only
    assert all("abstract" not in bib[key] for key in title_only)
    with np.load(_index_dir(bib) / "default.npz") as data:
        matrix = data["matrix"]
    assert matrix.shape == (len(bib), 1024)
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0)


def test_rebuild_reuses_unchanged_vectors(bib):
    """A second run embeds only what changed, prunes what is gone, and
    leaves everything else alone."""
    bib.build_semantic_indexes()
    before_keys = list(_manifest(bib)["entries"])
    before = np.load(_index_dir(bib) / "default.npz")["matrix"]
    bib["GoerzQ2022"]["abstract"] = "an entirely different abstract"
    del bib["BrifNJP2010"]
    bib["New2026"] = Entry("article", "New2026", fields={"title": "A title"})
    bib.save()
    report = bib.build_semantic_indexes()["default"]
    assert sorted(report["embedded"]) == ["GoerzQ2022", "New2026"]
    assert report["pruned"] == ["BrifNJP2010"]
    assert report["unchanged"] == len(bib) - 2
    after_keys = list(_manifest(bib)["entries"])
    after = np.load(_index_dir(bib) / "default.npz")["matrix"]
    assert "BrifNJP2010" not in after_keys
    unchanged = "KochEPJQT2022"
    assert np.array_equal(
        after[after_keys.index(unchanged)],
        before[before_keys.index(unchanged)],
    )


def test_unchanged_library_embeds_nothing(bib, embedder):
    """Re-indexing an untouched library embeds no text at all."""
    bib.build_semantic_indexes()
    embedder.calls.clear()
    report = bib.build_semantic_indexes()["default"]
    assert embedder.calls == []
    assert report["embedded"] == []
    assert report["unchanged"] == len(bib)


def test_changed_definition_rebuilds_the_index(bib, embedder):
    """Editing an index definition is one rebuild, not a thousand hash
    mismatches: the fingerprint carries the source list."""
    config.active.semantic.indexes = {"titles": ["title"]}
    bib.build_semantic_indexes()
    embedder.calls.clear()
    config.active.semantic.indexes = {"titles": ["title", "keywords"]}
    report = bib.build_semantic_indexes()["titles"]
    assert len(report["embedded"]) == len(bib)
    assert report["unchanged"] == 0


def test_progress_is_reported_per_entry(bib):
    """The progress hook is offered every index with its workload, and
    the callable it returns counts off the entries as they finish."""
    config.active.semantic.indexes = {"titles": ["title"]}
    calls = []
    steps = {}

    def progress(name, total):
        calls.append((name, total))
        steps[name] = 0

        def step(count):
            steps[name] += count

        return step

    report = bib.build_semantic_indexes(progress=progress)
    assert calls == [("default", len(bib)), ("titles", len(bib))]
    assert steps == {"default": len(bib), "titles": len(bib)}
    # A second run has nothing to embed, so every total is zero.
    calls.clear()
    bib.build_semantic_indexes(progress=progress)
    assert calls == [("default", 0), ("titles", 0)]
    assert report["default"]["unchanged"] == 0


def test_progress_hook_may_decline(bib):
    """Returning `None` from the hook is allowed and embeds as usual."""
    report = bib.build_semantic_indexes(progress=lambda name, total: None)
    assert len(report["default"]["embedded"]) == len(bib)


def test_batch_size_is_in_the_fingerprint(bib, monkeypatch):
    """The batch size changes the vectors in the fourth decimal, so it
    is recorded, and building with another one rebuilds rather than
    mixing vectors from the two."""
    bib.build_semantic_indexes()
    assert _manifest(bib)["fingerprint"]["batch"] == semantic._BATCH_SIZE
    monkeypatch.setattr(semantic, "embedder", lambda: StubEmbedder(batch=1))
    report = bib.build_semantic_indexes()["default"]
    assert len(report["embedded"]) == len(bib)
    assert report["unchanged"] == 0
    assert _manifest(bib)["fingerprint"]["batch"] == 1


def test_index_from_an_asset_class(bib, tmp_path):
    """An index source may name an `[assets]` class, whose file
    content is embedded as-is; an entry without the file is omitted."""
    config.active.assets = {"summary": "%f{Cite Key}_summary.md"}
    config.active.semantic.indexes = {"summary": "summary"}
    (tmp_path / "GoerzQ2022_summary.md").write_text(
        "# Krotov\n\nGradient based optimization of quantum gates.\n",
        encoding="utf-8",
    )
    report = bib.build_semantic_indexes()
    assert report["summary"]["embedded"] == ["GoerzQ2022"]
    manifest = _manifest(bib, "summary")
    assert list(manifest["entries"]) == ["GoerzQ2022"]
    assert manifest["fingerprint"]["sources"] == ["summary"]


def test_asset_class_shadows_a_field(bib, tmp_path):
    """A source name that is both an asset class and a field resolves
    to the asset."""
    config.active.assets = {"note": "%f{Cite Key}_note.md"}
    config.active.semantic.indexes = {"notes": "note"}
    (tmp_path / "GoerzQ2022_note.md").write_text("from the asset file")
    bib["GoerzQ2022"]["note"] = "from the field"
    bib.save()
    bib.build_semantic_indexes()
    text, used = semantic.row_text(
        bib["GoerzQ2022"],
        ("note",),
        lambda entry, name: bib._semantic_source_text(
            entry, name, {}, Path(bib.path).parent
        ),
    )
    assert used == ["note"]
    assert text == "from the asset file"


def test_unknown_source_is_an_error(bib):
    """A source that is neither an asset class nor a known field is a
    configuration error."""
    config.active.semantic.indexes = {"bogus": ["nonsense"]}
    with pytest.raises(ValueError, match="invalid semantic index source"):
        bib.build_semantic_indexes()


def test_index_dir_is_configurable(bib, tmp_path):
    """`index_dir` overrides the location derived from the .bib
    path."""
    config.active.semantic.index_dir = "vectors"
    bib.build_semantic_indexes()
    assert (tmp_path / "vectors" / "default.json").is_file()
    assert not (tmp_path / "refs.semantic").exists()


def test_index_needs_a_saved_library():
    """Indexes live beside the .bib file, so an unsaved library has
    nowhere to put them."""
    bib = Library()
    with pytest.raises(ValueError, match="requires a library with a file"):
        bib.build_semantic_indexes()


def test_long_text_is_chunked_and_pooled(bib, embedder, monkeypatch):
    """A text over the model's input length is split into chunks that
    each fit, and its vector is the normalized mean of theirs."""
    monkeypatch.setattr(semantic, "_TOKEN_BUDGET", 10)
    body = "\n\n".join(
        f"## Section {number}\n\n" + " ".join(["word"] * 8)
        for number in range(4)
    )
    chunks = semantic._chunks(body, embedder)
    assert len(chunks) > 1
    assert all(embedder.count_tokens(chunk) <= 10 for chunk in chunks)
    assert " ".join(chunks).split() == body.split()
    pooled = semantic._embed_documents([body], embedder)[0]
    expected = embedder.embed_documents(chunks).mean(axis=0)
    assert np.allclose(pooled, expected / np.linalg.norm(expected))


def test_oversized_paragraph_is_split_at_words(bib, embedder, monkeypatch):
    """A single paragraph over the budget is split as a last resort."""
    monkeypatch.setattr(semantic, "_TOKEN_BUDGET", 5)
    chunks = semantic._chunks(" ".join(["word"] * 12), embedder)
    assert [len(chunk.split()) for chunk in chunks] == [5, 5, 2]


# -- semantic search --------------------------------------------------- #


@pytest.fixture(name="toy")
def fixture_toy(tmp_path):
    """A small library whose titles make the expected ranking
    obvious, indexed and ready to query."""
    bib = Library()
    titles = {
        "Rydberg2020": "Rydberg blockade entangling gates neutral atoms",
        "Rydberg2021": "blockade gates for neutral atoms in tweezers",
        "Cooling1998": "evaporative cooling of a dilute bosonic vapor",
        "Krotov2019": "Krotov gradient optimization of pulse shapes",
        "Landscape2011": "control landscape topology of quantum systems",
    }
    for key, title in titles.items():
        bib[key] = Entry("article", key, fields={"title": title})
    # Findable lexically by its author, whom no title mentions.
    bib["Tannor2007"] = Entry(
        "book",
        "Tannor2007",
        fields={
            "author": "Tannor, David J.",
            "title": "a time dependent perspective on molecular dynamics",
        },
    )
    # No source of the default index, so no row in it at all.
    bib["Loose2020"] = Entry(
        "misc", "Loose2020", fields={"note": "an unindexable stray remark"}
    )
    bib.save(tmp_path / "refs.bib")
    bib.build_semantic_indexes()
    return bib


def test_search_finds_the_related_entries(toy):
    """A query ranks the entries sharing its vocabulary, and leaves
    the unrelated bulk out."""
    results = toy.semantic_search("neutral atoms blockade gates")
    keys = [entry.key for entry, _ in results]
    assert set(keys) == {"Rydberg2020", "Rydberg2021"}
    assert all(0.0 < cosine <= 1.0 for _, cosine in results)


def test_search_returns_nothing_for_an_unrelated_query(toy):
    """A query unrelated to the library is all bulk and no tail, which
    is the correct answer, not the ten least unrelated entries."""
    assert toy.semantic_search("mesoamerican pottery kilns") == []


def test_search_honors_the_limit(toy):
    """`limit` is a maximum, not a promise."""
    results = toy.semantic_search("blockade gates neutral atoms", limit=1)
    assert len(results) == 1


def test_hybrid_ranking_includes_lexical_only_hits(toy):
    """An entry the semantic leg drops can still rank through the
    lexical leg: no title or abstract mentions the author searched
    for, so only `search` finds the book."""
    assert toy.semantic_search("Tannor", hybrid=False) == []
    hybrid = toy.semantic_search("Tannor", hybrid=True)
    assert [entry.key for entry, _ in hybrid] == ["Tannor2007"]


def test_entry_outside_the_index_has_no_cosine(toy):
    """An entry no source of the index covers is absent from it, and
    ranks through the lexical leg with a null cosine."""
    assert "Loose2020" not in _manifest(toy)["entries"]
    results = toy.semantic_search("unindexable stray remark")
    ranked = {entry.key: cosine for entry, cosine in results}
    assert ranked["Loose2020"] is None


def test_search_without_hybrid_is_ordered_by_cosine(toy):
    """Without fusion the order is the cosine order."""
    results = toy.semantic_search("blockade gates neutral atoms", hybrid=False)
    cosines = [cosine for _, cosine in results]
    assert cosines == sorted(cosines, reverse=True)


def test_search_reports_no_floating_point_warnings(toy):
    """The similarity products run with floating-point error
    reporting off (macOS's Accelerate BLAS raises the flags
    spuriously), so no such warning reaches the user."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        assert toy.semantic_search("blockade gates neutral atoms")


def test_search_needs_a_built_index(bib):
    """Querying before indexing names the command that fixes it."""
    with pytest.raises(ValueError, match="run build_semantic_indexes"):
        bib.semantic_search("quantum control")


def test_search_rejects_an_undefined_index(toy):
    """An index name that no definition covers is an error."""
    with pytest.raises(ValueError, match="undefined semantic index"):
        toy.semantic_search("gates", index="nonexistent")


def test_stale_entries_are_warned_about(toy):
    """A changed entry is still ranked, with its stored vector, and
    the warning names it."""
    toy["Cooling1998"]["title"] = "something completely different"
    toy.save()
    with pytest.warns(UserWarning, match="Cooling1998"):
        toy.semantic_search("blockade gates neutral atoms")


# -- relevance scoring ------------------------------------------------- #


TOPICS = {
    "Gates": "entangling gates for neutral atoms via Rydberg blockade",
    "Cooling": "evaporative cooling of dilute bosonic vapors in traps",
}


@pytest.fixture(name="scored")
def fixture_scored(tmp_path):
    """A two-topic library with abstracts, indexed for scoring. Each
    paper is its topic's phrase plus one word of its own, so the two
    topics are far apart and the papers within one are close."""
    bib = Library()
    bib.save(tmp_path / "refs.bib")
    for topic, phrase in TOPICS.items():
        for number in range(12):
            key = f"{topic}{2000 + number}"
            bib[key] = Entry(
                "article",
                key,
                fields={
                    "title": f"{phrase} {topic.lower()}{number}",
                    "abstract": f"{phrase} {topic.lower()}{number}",
                },
            )
            bib.add_to_keyword(topic, key)
    bib.save()
    bib.build_semantic_indexes()
    return bib


def _candidate(topic, marker="fresh"):
    """A candidate paper on `topic`, worded like its members."""
    return f"{TOPICS[topic]} {marker}"


def test_score_is_a_percentile(scored):
    """A candidate on one of the library's topics scores like the
    library's own papers; an unrelated one scores at the bottom."""
    related = scored.semantic_score(_candidate("Gates"))
    unrelated = scored.semantic_score("mesoamerican pottery kilns")
    assert unrelated["score"] == 0.0
    assert 0.0 < related["score"] <= 100.0


def test_score_reports_the_nearest_entries(scored):
    """`nearest` lists exactly the neighbors the raw measure
    averages, best first, and there is no band without a
    collection."""
    report = scored.semantic_score(_candidate("Cooling"), k=3)
    assert len(report["nearest"]) == 3
    cosines = [item["cosine"] for item in report["nearest"]]
    assert cosines == sorted(cosines, reverse=True)
    assert all(item["key"].startswith("Cooling") for item in report["nearest"])
    assert "members" not in report


def test_score_against_a_collection(scored):
    """A collection restricts both the neighbors and what the score
    means, and adds the members' own band."""
    keys = [entry.key for entry in scored.search("Cooling", fields="keywords")]
    assert len(keys) == 12
    report = scored.semantic_score(_candidate("Cooling"), keys=keys)
    off_topic = scored.semantic_score(_candidate("Gates"), keys=keys)
    assert all(item["key"] in keys for item in report["nearest"])
    band = report["members"]
    assert 0.0 <= band["q1"] <= band["median"] <= band["q3"] <= 100.0
    assert report["score"] >= band["q1"] > off_topic["score"]


def test_score_clamps_k_to_the_collection(scored):
    """A single key is a collection of one, so the measure is the
    plain cosine and `nearest` holds that one entry."""
    report = scored.semantic_score(_candidate("Gates"), keys=["Gates2000"])
    assert [item["key"] for item in report["nearest"]] == ["Gates2000"]


def test_score_rejects_an_unknown_key(scored):
    """An unknown citation key is a `KeyError`."""
    with pytest.raises(KeyError):
        scored.semantic_score("anything", keys=["NoSuchKey"])


def test_probes_exclude_title_only_rows(scored):
    """Only rows shaped like an incoming candidate calibrate: a
    title-only entry is not among the probes."""
    scored["NoAbstract2026"] = Entry(
        "article", "NoAbstract2026", fields={"title": "no abstract here"}
    )
    scored.save()
    scored.build_semantic_indexes()
    index = semantic.load_index(_index_dir(scored), "default")
    probe_keys, probe_matrix = semantic._probes(index)
    assert "NoAbstract2026" not in probe_keys
    assert len(probe_keys) == len(probe_matrix) == len(scored) - 1


def test_score_against_a_separate_index(scored):
    """Scoring against an index whose rows are in another register
    still works: the probes are depressed identically, so the
    percentile stays comparable."""
    config.active.semantic.indexes = {"titles": ["title"]}
    config.active.semantic.score_index = "titles"
    scored.build_semantic_indexes()
    report = scored.semantic_score(_candidate("Gates"))
    assert 0.0 < report["score"] <= 100.0
    assert all(item["key"].startswith("Gates") for item in report["nearest"])


def test_empty_collection_warns(scored):
    """A collection the index holds no row for cannot be scored, and
    the caller is told rather than handed a bare 0."""
    scored["Loose2020"] = Entry(
        "misc", "Loose2020", fields={"note": "no indexable text"}
    )
    scored.save()
    with pytest.warns(semantic.EmptyCollectionWarning, match="no row"):
        report = scored.semantic_score("anything", keys=["Loose2020"])
    assert report["score"] == 0.0
    assert report["nearest"] == []


def test_small_collection_warns_about_the_band(scored):
    """The in-group band from a handful of members is flagged, since
    quartiles of that many numbers say little."""
    few = [f"Gates{2000 + n}" for n in range(3)]
    with pytest.warns(semantic.SmallCollectionWarning, match="only 3"):
        report = scored.semantic_score(_candidate("Gates"), keys=few)
    assert report["members"] is not None
    # A collection large enough for quartiles is not flagged.
    many = [f"Gates{2000 + n}" for n in range(12)]
    with warnings.catch_warnings():
        warnings.simplefilter("error", semantic.SmallCollectionWarning)
        scored.semantic_score(_candidate("Gates"), keys=many)

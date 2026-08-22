"""Tests for the semantic indexing feature: index building and
staleness, semantic/hybrid search, and relevance scoring.

Everything runs end to end against the real model's vectors, replayed
from the recording in `embeddings.npz` (see `embeddings.py`), so the
chunking, the match cut, and the calibration are exercised on the
geometry they will actually meet, offline and without the `semantic`
extra installed. A fixture whose text changes needs `make
record-embeddings`.
"""

import json
import shutil
import warnings
from pathlib import Path

import numpy as np
import pytest
from embeddings import Embedder

import bibdeskparser.config as config
import bibdeskparser.semantic as semantic
from bibdeskparser import Entry, Library

REFS_DIR = Path(__file__).parent / "Refs"

#: A multi-topic bibliography: 25 published papers for each of five
#: topics far enough apart that no paper of one is a plausible member
#: of another, each carrying its topic as its only keyword.
TOPICS_BIB = Path(__file__).parent / "topics.bib"

#: One further paper per topic, kept out of `TOPICS_BIB` so that
#: scoring it against the corpus cannot find itself.
CANDIDATES = Library(Path(__file__).parent / "topics_candidates.bib")

#: The topics of the corpus, in the order their sections appear.
TOPICS = (
    "SC Qubits",
    "Trapped Ion QC",
    "Atom Interferometry",
    "Spin Squeezing",
    "NV-Centers",
)

#: A query per topic, phrased as a reader would ask for it rather than
#: in the words the papers use.
QUERIES = {
    "SC Qubits": "microwave driven Josephson junction circuits for "
    "quantum logic",
    "Trapped Ion QC": "laser driven entangling gates on ions in a "
    "linear chain",
    "Atom Interferometry": "matter wave interferometer measuring "
    "inertial forces",
    "Spin Squeezing": "reducing projection noise below the standard "
    "quantum limit",
    "NV-Centers": "nitrogen vacancy defects in diamond as magnetometers",
}

#: Queries from outside the corpus' field altogether.
UNRELATED = (
    "mesoamerican pottery kilns and glaze chemistry",
    "sourdough fermentation and gluten development",
)

#: The model's vector length.
DIM = 384


@pytest.fixture(autouse=True)
def _recorded_embedder(monkeypatch):
    """Make every code path that reaches for the embedding model get
    the recorded one instead."""
    embed = Embedder()
    monkeypatch.setattr(semantic, "embedder", lambda: embed)
    return embed


@pytest.fixture(name="embedder")
def fixture_embedder(_recorded_embedder):
    """The recorded embedder in use, for tests that inspect what was
    embedded."""
    return _recorded_embedder


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
    path = Path(bib.path)
    return path.parent / f"{path.stem}.semantic"


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
    assert matrix.shape == (len(bib), DIM)
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
    monkeypatch.setattr(semantic, "embedder", lambda: Embedder(batch=1))
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


def test_library_asset_is_not_a_source(bib, tmp_path):
    """A library asset is one text for the whole library, so it would
    contribute the same words to every row."""
    (tmp_path / "topics.md").write_text("all about quantum control")
    config.active.assets = {"topics": "topics.md"}
    config.active.semantic.indexes = {"topics": "topics"}
    with pytest.raises(ValueError, match="a library asset is one text"):
        bib.build_semantic_indexes()


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


def _sentences(count, subject):
    """`count` sentences of plausible prose about `subject`."""
    return " ".join(
        f"The {subject} of stage {number} is optimized under a "
        f"bandwidth constraint."
        for number in range(count)
    )


def _long_summary(sections=4):
    """A markdown summary well past the model's input length, whose
    individual sections each fit within it."""
    return "\n\n".join(
        f"## Stage {number}\n\n{_sentences(20, 'pulse shape')}"
        for number in range(sections)
    )


def test_a_text_over_the_input_limit_is_chunked(embedder):
    """The one test that a stub cannot stand in for. The tokenizer
    truncates at the model's input length, so `count_tokens` reports
    exactly the budget for a text of 512 tokens and for one of 5000
    alike. Reading that as a fit would return the text whole and embed
    only its head."""
    text = _long_summary()
    assert embedder.count_tokens(text) == semantic._TOKEN_BUDGET
    chunks = semantic._chunks(text, embedder)
    assert len(chunks) > 1
    assert all(
        embedder.count_tokens(chunk) < semantic._TOKEN_BUDGET
        for chunk in chunks
    )


def test_long_text_is_chunked_and_pooled(embedder):
    """The chunks of an over-long text carry all of its words, and its
    vector is the normalized mean of theirs."""
    text = _long_summary()
    chunks = semantic._chunks(text, embedder)
    assert " ".join(chunks).split() == text.split()
    pooled = semantic._embed_documents([text], embedder)[0]
    expected = np.mean(list(embedder.embed_documents(chunks)), axis=0)
    assert np.allclose(pooled, expected / np.linalg.norm(expected))


def test_oversized_paragraph_is_split_at_words(embedder):
    """A single paragraph over the budget offers no heading and no
    blank line, so it is split between words as a last resort."""
    text = _sentences(60, "amplitude")
    assert embedder.count_tokens(text) == semantic._TOKEN_BUDGET
    chunks = semantic._chunks(text, embedder)
    assert len(chunks) > 1
    assert " ".join(chunks) == text


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


def test_search_honors_the_limit(toy):
    """`limit` is a maximum, not a promise."""
    results = toy.semantic_search("blockade gates neutral atoms", limit=1)
    assert len(results) == 1


def test_hybrid_ranking_includes_lexical_only_hits(toy):
    """An entry the semantic leg drops can still rank through the
    lexical leg: no title mentions the author searched for, so only
    `search` finds the book. Its cosine is reported as `None` even
    though the index holds a row for it, because the row's cosine is
    one the match cut rejected, and reporting it would present a
    non-match as a match."""
    key = "Tannor2007"
    assert key in _manifest(toy)["entries"]
    semantic_only = toy.semantic_search("Tannor", hybrid=False)
    assert key not in [entry.key for entry, _ in semantic_only]
    assert (toy[key], None) in toy.semantic_search("Tannor", hybrid=True)


def test_deleted_entries_drop_out_of_the_ranking(toy):
    """An index built before an entry was deleted still holds its row,
    and that row can rank. There is no entry to return for it, so it
    is left out rather than raising."""
    key = "Rydberg2020"
    del toy[key]
    toy.save()
    assert key in _manifest(toy)["entries"]
    with pytest.warns(UserWarning, match=key):
        results = toy.semantic_search("neutral atoms blockade gates")
    assert key not in [entry.key for entry, _ in results]


def test_search_rejects_a_limit_below_one(toy):
    """A limit of zero would ask for the best nothing."""
    with pytest.raises(ValueError, match="limit must be at least 1"):
        toy.semantic_search("gates", limit=0)


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


@pytest.fixture(name="scored")
def fixture_scored(tmp_path):
    """The topic corpus, indexed for scoring."""
    bib = Library(shutil.copy(TOPICS_BIB, tmp_path))
    bib.build_semantic_indexes()
    return bib


def _candidate(topic):
    """The held-out paper of `topic`, as the title and abstract of an
    incoming candidate. It is deliberately absent from the corpus, so
    scoring it cannot find itself."""
    key = CANDIDATES.keys(keyword=topic)[0]
    entry = CANDIDATES[key]
    return f"{entry['title']}\n\n{entry['abstract']}"


def test_score_is_a_percentile(scored):
    """A candidate on one of the library's topics scores like the
    library's own papers; one from outside the field scores at the
    bottom, though its raw cosine sits in the usual compressed band,
    which is the whole reason the percentile exists."""
    related = scored.semantic_score(_candidate("NV-Centers"))
    unrelated = scored.semantic_score(UNRELATED[0])
    assert unrelated["score"] == 0.0
    assert 0.4 < unrelated["nearest"][0]["cosine"] < 0.7
    assert 0.0 < related["score"] <= 100.0


def test_score_reports_the_nearest_entries(scored):
    """`nearest` lists exactly the neighbors the raw measure
    averages, best first, and there is no band without a
    collection. Against the whole corpus they are the candidate's own
    topic, which is the ranking doing its job."""
    topic = "Atom Interferometry"
    report = scored.semantic_score(_candidate(topic), k=3)
    assert len(report["nearest"]) == 3
    cosines = [item["cosine"] for item in report["nearest"]]
    assert cosines == sorted(cosines, reverse=True)
    assert all(
        scored[item["key"]].keywords == (topic,) for item in report["nearest"]
    )
    assert "members" not in report


def test_score_against_a_collection(scored):
    """A collection restricts both the neighbors and what the score
    means, and adds the members' own band. A paper of that topic
    reaches the band; one from another topic falls below it."""
    topic = "Atom Interferometry"
    keys = list(scored.keys(keyword=topic))
    assert len(keys) == 25
    report = scored.semantic_score(_candidate(topic), keys=keys)
    off_topic = scored.semantic_score(_candidate("SC Qubits"), keys=keys)
    assert all(item["key"] in keys for item in report["nearest"])
    band = report["members"]
    assert 0.0 <= band["q1"] <= band["median"] <= band["q3"] <= 100.0
    assert report["score"] >= band["q1"] > off_topic["score"]


def test_score_clamps_k_to_the_collection(scored):
    """A single key is a collection of one, so the measure is the
    plain cosine and `nearest` holds that one entry."""
    one = scored.keys(keyword="Spin Squeezing")[0]
    report = scored.semantic_score(_candidate("Spin Squeezing"), keys=[one])
    assert [item["key"] for item in report["nearest"]] == [one]


def test_score_rejects_an_unknown_key(scored):
    """An unknown citation key is a `KeyError`."""
    with pytest.raises(KeyError):
        scored.semantic_score("anything", keys=["NoSuchKey"])


def test_score_rejects_a_k_below_one(scored):
    """A `k` of zero would average no neighbors at all."""
    with pytest.raises(ValueError, match="k must be at least 1"):
        scored.semantic_score(_candidate("NV-Centers"), k=0)


def test_score_counts_a_repeated_key_once(scored):
    """A key named twice -- as it is whenever two groups overlap --
    would otherwise be listed twice among the neighbors, counted twice
    by the top-k mean, and leave its own cosine of 1.0 in the null
    distribution."""
    keys = list(scored.keys(keyword="NV-Centers"))[:4]
    once = scored.semantic_score(_candidate("NV-Centers"), keys=keys, k=2)
    twice = scored.semantic_score(
        _candidate("NV-Centers"), keys=keys + keys[:1], k=2
    )
    assert once == twice


def test_score_without_probes_is_none(tmp_path):
    """No entry carries an abstract, so no row of the default index is
    shaped like a candidate and there is nothing to calibrate
    against. A bare 0.0 would be indistinguishable from a genuinely
    unrelated candidate."""
    bib = Library()
    bib.save(tmp_path / "refs.bib")
    for number in range(4):
        key = f"Title{2000 + number}"
        bib[key] = Entry(
            "article", key, fields={"title": f"a quantum gate {number}"}
        )
    bib.save()
    bib.build_semantic_indexes()
    with pytest.warns(semantic.UncalibratedWarning, match="calibrate"):
        report = bib.semantic_score("a quantum gate")
    assert report["score"] is None
    assert report["nearest"]


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
    still works: a title is much shorter than a title and abstract, so
    every raw cosine drops, but the probes are depressed identically
    and the percentile stays comparable."""
    topic = "NV-Centers"
    config.active.semantic.indexes = {"titles": ["title"]}
    config.active.semantic.score_index = "titles"
    scored.build_semantic_indexes()
    report = scored.semantic_score(_candidate(topic), k=5)
    assert 0.0 < report["score"] <= 100.0
    on_topic = [
        item
        for item in report["nearest"]
        if scored[item["key"]].keywords == (topic,)
    ]
    assert len(on_topic) > len(report["nearest"]) / 2
    assert all(item["cosine"] < 0.9 for item in report["nearest"])


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
    members = list(scored.keys(keyword="SC Qubits"))
    with pytest.warns(semantic.SmallCollectionWarning, match="only 3"):
        report = scored.semantic_score(
            _candidate("SC Qubits"), keys=members[:3]
        )
    assert report["members"] is not None
    # A collection large enough for quartiles is not flagged.
    with warnings.catch_warnings():
        warnings.simplefilter("error", semantic.SmallCollectionWarning)
        scored.semantic_score(_candidate("SC Qubits"), keys=members)


# -- the corpus end to end --------------------------------------------- #
#
# The tests above pin behavior on libraries small enough to reason
# about entry by entry. These run the same code over a 125-paper
# bibliography, where the match cut and the calibration meet the cosine
# distribution they were designed for, and check the two things the
# feature is actually for: a search finds the topic asked about, and a
# candidate is placed with the papers it belongs among.


@pytest.mark.parametrize("topic", TOPICS)
def test_search_finds_the_queried_topic(scored, topic):
    """A query phrased in a reader's own words returns papers of the
    topic it describes: the best hit carries its keyword, and so do
    most of the rest.

    Not all of them, and the keyword is the cruder of the two
    judgments where they disagree. The query about inertial forces
    turns up a gravimeter paper filed under NV centers, which is a
    correct answer to the question that was asked and a wrong keyword
    for it; one paper per query is off-topic on either reading."""
    results = scored.semantic_search(QUERIES[topic])
    assert results
    assert results[0][0].keywords == (topic,)
    on_topic = [entry for entry, _ in results if entry.keywords == (topic,)]
    assert len(on_topic) >= 2 * len(results) / 3


@pytest.mark.parametrize("query", UNRELATED)
def test_search_ignores_a_query_from_another_field(scored, query):
    """Nothing in the corpus stands out from the background for a
    query about something else entirely, so the answer is empty rather
    than the ten least unrelated papers."""
    assert scored.semantic_search(query) == []


@pytest.mark.parametrize("topic", TOPICS)
def test_score_is_highest_against_the_candidate_own_topic(scored, topic):
    """The measure the feature exists to provide: a paper held out of
    the corpus scores higher against the topic it belongs to than
    against any of the other four."""
    candidate = _candidate(topic)
    scores = {}
    for against in TOPICS:
        keys = scored.keys(keyword=against)
        scores[against] = scored.semantic_score(candidate, keys=keys)["score"]
    assert max(scores, key=scores.get) == topic


def test_score_recognizes_a_paper_already_in_the_library(scored):
    """A candidate that is already an entry scores near the top with a
    nearest-neighbor cosine of 1.0, which is what makes the score
    usable as a duplicate check."""
    key = scored.keys(keyword="NV-Centers")[0]
    entry = scored[key]
    report = scored.semantic_score(
        f"{entry['title']}\n\n{entry['abstract']}", k=3
    )
    assert report["nearest"][0] == {"key": key, "cosine": 1.0}
    assert report["score"] > 90.0

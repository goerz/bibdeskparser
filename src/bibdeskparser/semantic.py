"""Embedding indexes, semantic search, and relevance scoring.

Backend for {meth}`bibdeskparser.Library.build_semantic_indexes`,
{meth}`bibdeskparser.Library.semantic_search`, and
{meth}`bibdeskparser.Library.semantic_score`; see the
[Semantic Indexing](semantic-indexing) page for the concepts.

An *index* is a matrix of L2-normalized embedding vectors, one row per
citation key, stored next to the `.bib` file together with a JSON
manifest. This module owns the vectors and the arithmetic on them; the
library-facing side (where the index directory is, which text a source
name contributes for an entry) lives in `library.py` and reaches in
here through the `rows` callback of {func}`build_indexes` and the
`lexical` argument of {func}`search`.

The package depends on neither `numpy` nor `fastembed`, so importing
this module is the point where the `bibdeskparser[semantic]` extra is
required. `numpy` is imported here; the embedding model is loaded on
first use, in {func}`embedder`.
"""

import dataclasses
import hashlib
import json
import re
import warnings

try:
    import numpy as np
except ImportError as _exc:  # pragma: no cover - depends on the install
    raise ImportError(
        "semantic indexing requires numpy; install bibdeskparser[semantic]"
    ) from _exc

__all__ = []

# All members whose name does not start with an underscore must be listed
# either in __all__ or in __private__
__private__ = [
    "DEFAULT_INDEX",
    "DEFAULT_SOURCES",
    "embedder",
    "row_text",
    "build_indexes",
    "load_index",
    "stale_keys",
    "search",
    "score",
    "EmptyCollectionWarning",
    "SmallCollectionWarning",
]

#: Fewest members whose own percentiles still make quartiles worth
#: reporting. Below this, the band is quartiles of a handful of
#: numbers and says more about the sample than about the collection.
_MIN_BAND_MEMBERS = 5


#: The name of the built-in index, which always exists and cannot be
#: redefined: its rows have the shape of an incoming candidate, which
#: is what makes it the probe set of {func}`score`.
DEFAULT_INDEX = "default"

#: The sources of the built-in index.
DEFAULT_SOURCES = ("title", "abstract")

#: The embedding model. Its ONNX export is a frozen artifact, so a
#: pinned `fastembed` release yields identical vectors run to run; the
#: index fingerprint records which release and which export built it.
_MODEL_NAME = "BAAI/bge-small-en-v1.5"

#: The instruction the `bge` family was trained to see in front of a
#: search query (and only there). `fastembed` does not apply it, so
#: {meth}`_Embedder.embed_query` prepends it explicitly.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

#: The model's input length in tokens. A longer text is chunked.
_TOKEN_BUDGET = 512

#: Scale factor turning a median absolute deviation into an estimate of
#: a standard deviation for normally distributed data.
_MAD_SCALE = 1.4826

#: How many outlier-resistant standard deviations above the median of
#: the cosine distribution an entry must score to count as a match.
_MATCH_CUT = 3.5

#: The rank offset of reciprocal rank fusion (Cormack, Clarke, and
#: Büttcher, SIGIR 2009), large enough that adjacent ranks are near
#: ties and agreement between the two legs outweighs a single leg's
#: top hit.
_RRF_OFFSET = 60

#: How many texts are handed to the model at once. Every sequence in a
#: batch is padded to the length of the longest one in it, so a smaller
#: batch wastes less computation on a corpus of mixed lengths, where a
#: one-word title may sit beside a 300-word abstract; it also makes
#: progress reporting fine-grained. The value changes the vectors in
#: the fourth decimal, through the order of floating-point
#: accumulation, which is why it is part of the index fingerprint.
_BATCH_SIZE = 16

#: Decimal places of a reported cosine. Cosines carry only relative
#: meaning within one query, so more digits would suggest a precision
#: they do not have.
_COSINE_DIGITS = 3


class EmptyCollectionWarning(UserWarning):
    """Scoring against a collection the index holds no row for. The
    reported score is not meaningful."""


class SmallCollectionWarning(UserWarning):
    """The in-group band was computed from very few members, so its
    quartiles carry little information."""


# -- the embedding model ---------------------------------------------- #


class _Embedder:
    """The embedding model, loaded on construction.

    Wraps `fastembed`'s `TextEmbedding` in the three operations the
    rest of this module needs: counting tokens (for chunking),
    embedding documents, and embedding a query. Both embedding methods
    produce L2-normalized `float32` vectors of `fingerprint["dim"]`
    components.
    """

    def __init__(self):
        try:
            # pylint: disable-next=import-outside-toplevel
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise ImportError(
                "semantic indexing requires fastembed; install "
                "bibdeskparser[semantic]"
            ) from exc
        # pylint: disable-next=import-outside-toplevel
        from importlib.metadata import version

        description = next(
            item
            for item in TextEmbedding.list_supported_models()
            if item["model"] == _MODEL_NAME
        )
        self.fingerprint = {
            "model": _MODEL_NAME,
            "repository": description["sources"]["hf"],
            "file": description["model_file"],
            "dim": description["dim"],
            "fastembed": version("fastembed"),
            "batch": _BATCH_SIZE,
        }
        self._model = TextEmbedding(_MODEL_NAME)

    def count_tokens(self, text):
        """The number of tokens `text` occupies in the model input."""
        return self._model.token_count(text)

    def embed_documents(self, texts):
        """The document vectors of `texts`, yielded in order.

        The model is fed `_BATCH_SIZE` texts at a time and yields a
        whole batch at once, so a caller can report progress at that
        granularity but no finer."""
        for vector in self._model.passage_embed(
            list(texts), batch_size=_BATCH_SIZE
        ):
            yield np.asarray(vector, dtype=np.float32)

    def embed_query(self, text):
        """The query vector of the search phrase `text`."""
        embedded = self._model.query_embed([_QUERY_PREFIX + text])
        return _as_matrix(embedded)[0]


_EMBEDDER = None


def embedder():
    """The process-wide {class}`_Embedder`, loaded on first use.

    Loading the model takes about a second, so a process that embeds
    more than once reuses it. The test suite replaces this function
    with one returning a stub, which is why every function here takes
    an embedder rather than reaching for the model itself.
    """
    global _EMBEDDER  # pylint: disable=global-statement
    if _EMBEDDER is None:
        _EMBEDDER = _Embedder()
    return _EMBEDDER


def _as_matrix(vectors, dim=0):
    """`vectors` (an iterable of 1-d arrays) as an `(N, dim)` float32
    array, keeping the shape well-defined when `N` is zero."""
    listed = list(vectors)
    if not listed:
        return np.zeros((0, dim), dtype=np.float32)
    return np.asarray(listed, dtype=np.float32)


def _rounded(cosine):
    """`cosine` rounded for reporting, or `None` if it is `None`."""
    return None if cosine is None else round(cosine, _COSINE_DIGITS)


def _similarities(matrix, other):
    """The matrix product `matrix @ other`, with floating-point error
    reporting off.

    Every operand here is a unit vector, so none of the conditions
    NumPy would report can actually arise; macOS's Accelerate BLAS
    nonetheless raises the divide/overflow/invalid flags for ordinary
    `matmul` calls, and the resulting warnings would surface on every
    search.
    """
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        return matrix @ other


def _normalized(vector):
    """`vector` scaled to unit length (unchanged if it is all zeros)."""
    norm = float(np.linalg.norm(vector))
    return vector if norm == 0.0 else vector / norm


# -- what gets embedded ------------------------------------------------ #


def row_text(entry, sources, source_text):
    """The text an index built from `sources` embeds for `entry`.

    `source_text(entry, name)` yields the text a single source
    contributes, or `None`/`""` if `entry` has nothing for it. Returns
    the pair `(text, used)`: the surviving contributions joined in
    `sources` order, separated by a blank line, and the list of the
    source names that actually contributed. An entry with `used ==
    []` has no row in the index.
    """
    used = []
    parts = []
    for name in sources:
        text = (source_text(entry, name) or "").strip()
        if text:
            used.append(name)
            parts.append(text)
    return "\n\n".join(parts), used


def _digest(text):
    """The SHA-256 hex digest of `text`, recorded in the manifest so
    that re-indexing can tell an unchanged row from a changed one."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: Splits markdown text before each ATX heading line.
_HEADING_RE = re.compile(r"^(?=#{1,6} )", re.MULTILINE)

#: Splits text at blank lines (paragraph boundaries).
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


def _split_sections(text):
    """`text` split before each markdown heading (separators kept)."""
    return [part for part in _HEADING_RE.split(text) if part.strip()]


def _split_paragraphs(text):
    """`text` split at blank lines."""
    return [part for part in _PARAGRAPH_RE.split(text) if part.strip()]


def _split_words(text):
    """`text` split at whitespace."""
    return text.split()


#: The splitters tried in turn, each with the string that rejoins its
#: pieces: headings first (a section boundary is the most meaningful
#: place to cut), then paragraphs, then -- as a last resort for a
#: single oversized paragraph -- individual words.
_SPLITTERS = (
    (_split_sections, ""),
    (_split_paragraphs, "\n\n"),
    (_split_words, " "),
)


def _chunks(text, embed, level=0):
    """`text` as a list of pieces that each fit `_TOKEN_BUDGET`.

    A text within the budget is returned whole. Otherwise it is split
    by the `level`-th splitter and the pieces are packed back together
    greedily, each chunk filled as close to the budget as it goes;
    a chunk that is still too long is split further by the next
    splitter. Packing toward the budget is deliberate: text that ends
    up in one chunk is combined by the model in context, whereas text
    in separate chunks is combined by the arithmetic mean of
    {func}`_embed_documents`, which is the cruder of the two.
    """
    if embed.count_tokens(text) <= _TOKEN_BUDGET:
        return [text]
    if level >= len(_SPLITTERS):
        # Nothing left to split on; the model truncates the tail.
        return [text]
    split, joiner = _SPLITTERS[level]
    pieces = split(text)
    if len(pieces) < 2:
        return _chunks(text, embed, level + 1)
    packed = []
    buffer = ""
    for piece in pieces:
        candidate = f"{buffer}{joiner}{piece}" if buffer else piece
        if buffer and embed.count_tokens(candidate) > _TOKEN_BUDGET:
            packed.append(buffer)
            buffer = piece
        else:
            buffer = candidate
    if buffer:
        packed.append(buffer)
    return [
        chunk for part in packed for chunk in _chunks(part, embed, level + 1)
    ]


def _embed_documents(texts, embed, step=None):
    """One unit vector per element of `texts`, as an `(N, dim)` array.

    A text longer than the model's input is chunked; its chunks are
    embedded separately and the chunk vectors are averaged and
    re-normalized into the single vector of that text.

    `step`, if given, is called with the number of texts finished
    since the previous call, as each text's vector becomes available.
    """
    if not texts:
        return _as_matrix([], dim=embed.fingerprint["dim"])
    chunked = [_chunks(text, embed) for text in texts]
    vectors = iter(
        embed.embed_documents(
            [chunk for chunks in chunked for chunk in chunks]
        )
    )
    pooled = []
    for chunks in chunked:
        block = [next(vectors) for _ in chunks]
        pooled.append(_normalized(np.mean(block, axis=0)))
        if step is not None:
            step(1)
    return _as_matrix(pooled, dim=embed.fingerprint["dim"])


# -- index files ------------------------------------------------------- #


@dataclasses.dataclass
class _Index:
    """One built index: `name` and the `sources` it was built from,
    the citation `keys` in row order of `matrix` (an `(N, dim)` array
    of unit vectors), the per-key `records` (`{"sources": [...],
    "hash": ...}`, which is what staleness compares), and the
    `fingerprint` of everything that influenced the vectors."""

    name: str
    sources: tuple
    keys: list
    matrix: "np.ndarray"
    records: dict
    fingerprint: dict


def _paths(index_dir, name):
    """The `(matrix, manifest)` file paths of index `name`."""
    return index_dir / f"{name}.npz", index_dir / f"{name}.json"


def _fingerprint(sources, embed):
    """Everything that determines the vectors of an index over
    `sources`: the source list plus the model's own fingerprint.
    Vectors from different fingerprints are never mixed; a mismatch
    rebuilds the index as a whole."""
    return {"sources": list(sources), **embed.fingerprint}


def load_index(index_dir, name):
    """The stored index `name` from `index_dir`, or `None` if it has
    not been built (or its two files disagree, which a rebuild
    fixes)."""
    matrix_path, manifest_path = _paths(index_dir, name)
    try:
        with open(manifest_path, encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        with np.load(matrix_path) as data:
            matrix = data["matrix"]
    except (OSError, ValueError, KeyError):
        return None
    records = manifest.get("entries", {})
    fingerprint = manifest.get("fingerprint", {})
    if len(records) != len(matrix):
        return None
    return _Index(
        name=name,
        sources=tuple(fingerprint.get("sources", ())),
        keys=list(records),
        matrix=matrix,
        records=records,
        fingerprint=fingerprint,
    )


def _save_index(index, index_dir):
    """Write `index` to `index_dir` as its `.npz`/`.json` pair."""
    matrix_path, manifest_path = _paths(index_dir, index.name)
    index_dir.mkdir(parents=True, exist_ok=True)
    np.savez(matrix_path, matrix=index.matrix)
    manifest = {"fingerprint": index.fingerprint, "entries": index.records}
    with open(manifest_path, "w", encoding="utf-8") as manifest_file:
        json.dump(manifest, manifest_file, indent=1, ensure_ascii=False)
        manifest_file.write("\n")


def build_indexes(index_dir, definitions, rows, embed=None, progress=None):
    """Build or refresh every index in `definitions`.

    `definitions` maps an index name to its tuple of sources, and
    `rows(sources)` yields the `(key, text, used)` triples an index
    over those sources covers (see {func}`row_text`). Returns the
    report described by
    {meth}`bibdeskparser.Library.build_semantic_indexes`.

    `progress`, if given, is called once per index, in the order the
    indexes are built, as `progress(name, total)` with the number of
    entries that index has to embed. It returns either `None` or a
    callable that is then invoked with the number of entries finished
    since the previous call.
    """
    embed = embed or embedder()
    return {
        name: _build_index(
            index_dir, name, sources, rows(sources), embed, progress
        )
        for name, sources in definitions.items()
    }


def _build_index(index_dir, name, sources, rows, embed, progress=None):
    """Build or refresh the single index `name`; see
    {func}`build_indexes`."""
    fingerprint = _fingerprint(sources, embed)
    stored = load_index(index_dir, name)
    if stored is not None and stored.fingerprint != fingerprint:
        stored = None  # a rebuild, not a thousand hash mismatches
    known = {} if stored is None else stored.records
    reusable = {} if stored is None else dict(zip(stored.keys, stored.matrix))
    keys = []
    records = {}
    fresh_keys = []
    fresh_texts = []
    for key, text, used in rows:
        record = {"sources": list(used), "hash": _digest(text)}
        keys.append(key)
        records[key] = record
        if known.get(key) != record or key not in reusable:
            fresh_keys.append(key)
            fresh_texts.append(text)
    step = None if progress is None else progress(name, len(fresh_texts))
    fresh = dict(zip(fresh_keys, _embed_documents(fresh_texts, embed, step)))
    matrix = _as_matrix(
        [fresh[key] if key in fresh else reusable[key] for key in keys],
        dim=embed.fingerprint["dim"],
    )
    index = _Index(
        name=name,
        sources=tuple(sources),
        keys=keys,
        matrix=matrix,
        records=records,
        fingerprint=fingerprint,
    )
    _save_index(index, index_dir)
    return {
        "embedded": fresh_keys,
        "pruned": sorted(set(known) - set(records)),
        "unchanged": len(keys) - len(fresh_keys),
    }


def stale_keys(index, rows):
    """The citation keys for which `index` is out of date: the ones
    whose source text has changed since it was built, the ones added
    to the library since, and the ones it no longer has. `rows` is
    the current `(key, text, used)` triples over `index.sources`."""
    current = {
        key: {"sources": list(used), "hash": _digest(text)}
        for key, text, used in rows
    }
    changed = {
        key
        for key, record in current.items()
        if index.records.get(key) != record
    }
    return sorted(changed | (set(index.records) - set(current)))


# -- semantic search --------------------------------------------------- #


def _match_cut(cosines):
    """The cosine an entry must exceed to count as a match.

    For any one query, nearly all of a mixed library is unrelated to
    it, so the cosines form a compact bulk of background similarity
    with the relevant entries, if any, above it as a thin tail. The
    cut sits `_MATCH_CUT` estimated standard deviations above the
    center of that bulk, located by the median and the median absolute
    deviation rather than by the mean and standard deviation: those
    tolerate up to half the values being outliers, so the matches
    cannot raise the center or widen the spread enough to hide
    themselves.
    """
    median = np.median(cosines)
    deviation = _MAD_SCALE * np.median(np.abs(cosines - median))
    return float(median + _MATCH_CUT * deviation)


def _fuse(legs, cosines):
    """The keys of `legs` (ranked lists) merged by reciprocal rank
    fusion: each leg contributes `1 / (_RRF_OFFSET + rank)` to the
    keys it ranks, and the sums are sorted descending. Only ranks
    enter, so the legs' incomparable scores need no calibration. Ties
    break by cosine, then by key."""
    fused = {}
    for leg in legs:
        for rank, key in enumerate(leg, start=1):
            fused[key] = fused.get(key, 0.0) + 1.0 / (_RRF_OFFSET + rank)
    return sorted(
        fused,
        key=lambda key: (-fused[key], -cosines.get(key, -1.0), key),
    )


def search(index, query, *, lexical=None, limit=10, embed=None):
    """Rank the entries of `index` against the search phrase `query`.

    Returns a list of `(key, cosine)` pairs, best first, at most
    `limit` long: the entries whose cosine passes {func}`_match_cut`,
    optionally fused with the ranking `lexical` (an ordered list of
    citation keys from the lexical `Library.search`). The reported
    cosine is the query-entry cosine, rounded, and is `None` for a key
    that only the lexical leg ranks.
    """
    embed = embed or embedder()
    if not index.keys:
        return []
    similarities = _similarities(index.matrix, embed.embed_query(query))
    cosines = dict(zip(index.keys, similarities.tolist()))
    cut = _match_cut(similarities)
    matched = sorted(
        (key for key in index.keys if cosines[key] > cut),
        key=lambda key: (-cosines[key], key),
    )[:limit]
    ranked = matched if lexical is None else _fuse([matched, lexical], cosines)
    return [(key, _rounded(cosines.get(key))) for key in ranked[:limit]]


# -- relevance scoring ------------------------------------------------- #


def _top_k_mean(similarities, k):
    """The mean of the `k` largest values of `similarities`. With a
    single target this is the plain cosine; over a collection it is
    the established zero-shot measure, where a single centroid would
    be mush on a multi-topic library."""
    if k <= 0 or len(similarities) == 0:
        return 0.0
    return float(np.partition(similarities, -k)[-k:].mean())


def _percentile(value, distribution):
    """`value` as a percentile of `distribution` (an array): the
    percentage of the distribution that falls below it."""
    if len(distribution) == 0:
        return 0.0
    return round(100.0 * float(np.mean(distribution < value)), 1)


def _probes(default_index):
    """The `(keys, matrix)` of the calibration probes: the rows of the
    default index that carry both title and abstract. A title-only row
    is not shaped like an incoming candidate, so it would not be
    scored the way a candidate is."""
    rows = [
        position
        for position, key in enumerate(default_index.keys)
        if tuple(default_index.records[key]["sources"]) == DEFAULT_SOURCES
    ]
    keys = [default_index.keys[row] for row in rows]
    return keys, default_index.matrix[rows]


def score(index, default_index, text, *, keys=None, k=10, embed=None):
    """Score the candidate `text` against `index`.

    The target is the whole index, or the rows of the citation `keys`
    it holds. `default_index` supplies the probes that calibrate the
    raw measure into a percentile. Returns the dict described by
    {meth}`bibdeskparser.Library.semantic_score`.
    """
    embed = embed or embedder()
    positions = {key: row for row, key in enumerate(index.keys)}
    target_keys = (
        index.keys
        if keys is None
        else [key for key in keys if key in positions]
    )
    target = index.matrix[[positions[key] for key in target_keys]]
    if not target_keys:
        warnings.warn(
            f"semantic index {index.name!r} holds no row for any of the "
            "given keys; the score is not meaningful",
            EmptyCollectionWarning,
            stacklevel=3,
        )
    k = min(k, len(target_keys))
    candidate = _embed_documents([text], embed)[0]
    similarities = _similarities(target, candidate)
    probe_keys, probe_matrix = _probes(default_index)
    nulls = _null_distribution(
        probe_keys, probe_matrix, target, target_keys, k
    )
    result = {
        "score": _percentile(_top_k_mean(similarities, k), nulls),
        "nearest": [
            {
                "key": target_keys[row],
                "cosine": _rounded(float(similarities[row])),
            }
            for row in np.argsort(-similarities)[:k]
        ],
    }
    if keys is not None:
        result["members"] = _member_band(probe_keys, nulls, set(target_keys))
    return result


def _null_distribution(probe_keys, probe_matrix, target, target_keys, k):
    """The raw measure of every probe against the same target under
    the same `k`, as an array: what each of the library's own papers
    would score had it arrived today as a fresh candidate. A probe
    that is itself in the target set is scored with its own row
    dropped from the target side."""
    positions = {key: row for row, key in enumerate(target_keys)}
    similarities = _similarities(probe_matrix, target.T)
    nulls = np.empty(len(probe_keys), dtype=np.float64)
    for row, key in enumerate(probe_keys):
        against = similarities[row]
        if key in positions:
            against = np.delete(against, positions[key])
        nulls[row] = _top_k_mean(against, min(k, len(against)))
    return nulls


def _member_band(probe_keys, nulls, members):
    """The quartiles of the percentiles of the target set's own
    members, or `None` if none of them is a probe. It turns a
    percentile into "would sit among these papers like one of their
    own"."""
    own = [
        _percentile(nulls[row], nulls)
        for row, key in enumerate(probe_keys)
        if key in members
    ]
    if not own:
        return None
    if len(own) < _MIN_BAND_MEMBERS:
        warnings.warn(
            f"the in-group band comes from only {len(own)} member(s); "
            "its quartiles say little about the collection",
            SmallCollectionWarning,
            stacklevel=4,
        )
    q1, median, q3 = np.percentile(own, [25, 50, 75])
    return {
        "q1": round(float(q1), 1),
        "median": round(float(median), 1),
        "q3": round(float(q3), 1),
    }

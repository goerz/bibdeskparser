"""The embedding model as the test suite sees it.

The semantic tests run the whole pipeline -- chunking, batching, the
match cut, the calibration -- against vectors recorded from the real
`BAAI/bge-small-en-v1.5`, so that the geometry under test is the
model's own while the suite itself needs neither the `semantic` extra
nor a network connection. `embeddings.npz` holds one vector per
embedded text and one token count per counted text, keyed by a digest
of the text and of what was asked of it.

A text the recording does not hold fails the test that needed it,
naming the text. Re-record after changing a fixture's text, the query
prefix, the model, or the chunking:

    make record-embeddings

That step needs `fastembed` (pulled in on the fly, not a development
dependency) and downloads the model on first use. It embeds only what
is missing and rewrites the file in place.
"""

import atexit
import hashlib
import json
import os
from pathlib import Path

import numpy as np

import bibdeskparser.semantic as semantic

#: Where the recorded vectors live.
CASSETTE = Path(__file__).parent / "embeddings.npz"

#: Set to record what the cassette is missing instead of failing.
RECORD_ENV_VAR = "BIBDESKPARSER_RECORD_EMBEDDINGS"


def _key(kind, text):
    """The cassette key of `text` under `kind` (`"doc"`, `"query"`,
    or `"tokens"`)."""
    digest = hashlib.sha256(f"{kind}\0{text}".encode("utf-8"))
    return digest.hexdigest()


class _Cassette:
    """The recorded vectors and token counts, and the real model
    behind them while recording."""

    def __init__(self):
        self.vectors = {}
        self.tokens = {}
        self.fingerprint = {}
        self.recording = bool(os.environ.get(RECORD_ENV_VAR))
        self._model = None
        self._dirty = False
        if CASSETTE.is_file():
            with np.load(CASSETTE, allow_pickle=False) as data:
                self.vectors = dict(
                    zip(data["vector_keys"].tolist(), data["vectors"])
                )
                self.tokens = dict(
                    zip(data["token_keys"].tolist(), data["tokens"].tolist())
                )
                self.fingerprint = json.loads(str(data["fingerprint"]))
        elif not self.recording:
            raise RuntimeError(
                f"{CASSETTE} is missing; run 'make record-embeddings'"
            )
        if self.recording and not self.fingerprint:
            _ = self.model  # for the fingerprint of a fresh recording

    @property
    def model(self):
        """The real model, loaded on first use while recording."""
        if self._model is None:
            self._model = semantic._Embedder()
            self.fingerprint = dict(self._model.fingerprint)
            self._dirty = True
        return self._model

    def _miss(self, what, text):
        shown = text if len(text) <= 200 else f"{text[:200]}..."
        raise RuntimeError(
            f"no recorded {what} for {shown!r}; the test fixtures have "
            f"changed, so run 'make record-embeddings'"
        )

    def count(self, text):
        """The model's token count of `text`."""
        key = _key("tokens", text)
        if key not in self.tokens:
            if not self.recording:
                self._miss("token count", text)
            self.tokens[key] = int(self.model.count_tokens(text))
            self._dirty = True
        return self.tokens[key]

    def documents(self, texts):
        """The document vectors of `texts`, in order."""
        missing = [
            text for text in texts if _key("doc", text) not in self.vectors
        ]
        if missing:
            if not self.recording:
                self._miss("vector", missing[0])
            # Embedded in one call, so that the recording is made under
            # the same batching a real build would use.
            for text, vector in zip(
                missing, self.model.embed_documents(missing)
            ):
                self.vectors[_key("doc", text)] = vector
            self._dirty = True
        return [self.vectors[_key("doc", text)] for text in texts]

    def query(self, text):
        """The query vector of the search phrase `text`."""
        # Keyed on the prefixed text, so that a change to the prefix
        # invalidates every recorded query vector.
        key = _key("query", semantic._QUERY_PREFIX + text)
        if key not in self.vectors:
            if not self.recording:
                self._miss("query vector", text)
            self.vectors[key] = self.model.embed_query(text)
            self._dirty = True
        return self.vectors[key]

    def save(self):
        """Write the cassette back if anything was recorded."""
        if not self._dirty:
            return
        keys = sorted(self.vectors)
        token_keys = sorted(self.tokens)
        np.savez_compressed(
            CASSETTE,
            vector_keys=np.asarray(keys),
            vectors=np.asarray(
                [self.vectors[key] for key in keys], dtype=np.float32
            ),
            token_keys=np.asarray(token_keys),
            tokens=np.asarray(
                [self.tokens[key] for key in token_keys], dtype=np.int32
            ),
            fingerprint=np.asarray(json.dumps(self.fingerprint)),
        )
        self._dirty = False


_CASSETTE = None


def cassette():
    """The process-wide {class}`_Cassette`, loaded on first use."""
    global _CASSETTE  # pylint: disable=global-statement
    if _CASSETTE is None:
        _CASSETTE = _Cassette()
        atexit.register(_CASSETTE.save)
    return _CASSETTE


class Embedder:
    """What `bibdeskparser.semantic.embedder()` returns under test:
    the real model's recorded answers, with the same interface.

    `calls` accumulates every text handed to {meth}`embed_documents`,
    for the tests that check what was embedded rather than what came
    back."""

    def __init__(self, batch=None):
        recorded = cassette().fingerprint
        self.fingerprint = {
            **recorded,
            "batch": semantic._BATCH_SIZE if batch is None else batch,
        }
        self.calls = []

    def count_tokens(self, text):
        """The number of tokens `text` occupies in the model input."""
        return cassette().count(text)

    def embed_documents(self, texts):
        """The document vectors of `texts`, yielded in order."""
        listed = list(texts)
        self.calls.extend(listed)
        yield from cassette().documents(listed)

    def embed_query(self, text):
        """The query vector of the search phrase `text`."""
        return cassette().query(text)

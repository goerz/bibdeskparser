(semantic-indexing)=

# Semantic Indexing

Machine learning methods for representing text, in particular the transformer-based *embedding models* developed over the past decade, make it possible to compare two passages by what they are about rather than by the words they happen to contain. BibDeskParser applies such a model to a BibDesk library: text (like the abstract, or a summary) belonging to each entry is mapped to a point in a high-dimensional space, so that questions of "relevance" become questions of the proximity of two "embedding vectors". This enables searching for entries in a library about a given topic description, independent of particular words appearing in papers. It also makes it possible to decide whether a newly posted preprint is similar to existing groups of papers in the library, and would add to the existing literature.

This page describes the machinery in the order in which it is applied: how text becomes a vector, how proximity between vectors is measured, how the package decides which of the resulting distances carry information, and what the reported numbers do and do not establish.

The feature requires the optional `semantic` extra, named in square brackets alongside the package:

```
pip install "bibdeskparser[semantic]"
uv add "bibdeskparser[semantic]"
uv tool install "bibdeskparser[semantic]"
```

A bare installation is unaffected and retains exactly the feature set it had. Three commands are provided: [`build_semantic_indexes`](cli-build-semantic-indexes) builds the vectors, while [`semantic_search`](cli-semantic-search) and [`semantic_score`](cli-semantic-score) use them. The corresponding Python methods are {py:meth}`~bibdeskparser.Library.build_semantic_indexes`, {py:meth}`~bibdeskparser.Library.semantic_search`, and {py:meth}`~bibdeskparser.Library.semantic_score`.

## Text as coordinates

An *embedding model* is a function from a multiline string to a short vector of floats. The model used here, `BAAI/bge-small-en-v1.5`, returns 384 floats for any input, so that every abstract, every summary, and every search phrase becomes a point in a 384-dimensional space. The model is trained on a large collection of text pairs known in advance to belong together, such as a question and the passage answering it, or a sentence and its paraphrase, under an objective that pulls the two members of a pair together and separates unrelated texts. Over enough such pairs, the arrangement that emerges is one in which proximity reflects meaning rather than spelling, which is why a query and a document can lie close together without sharing a single word.

The 384 numbers are best understood as coordinates rather than as named features. No individual component corresponds to "quantum optics"; the information is distributed over all of them, and no interpretation of any one of them is required.

The model is evaluated on the CPU through [fastembed](https://github.com/qdrant/fastembed), with no GPU, no server process, and no PyTorch installation. The first use downloads about 130 MB of model files into a local cache, after which the package requires no network access. Embedding a thousand entries takes roughly a minute on a laptop, and a single query well under a second.

The model used here was originally trained on generic English text, and is not specialized to the usual academic context of a bibliographic library. It is used exactly as distributed, without any fitting step, which is what makes the feature inexpensive and reproducible.

## Measuring proximity

Every vector the model produces is scaled to unit length. For two unit vectors $u$ and $v$, the dot product between the vectors is directly the cosine of the angle between them, equal to 1 for identical directions and 0 for perpendicular ones. Similarity is thus an angle, and the length of a text has already been divided out.

This makes retrieval inexpensive. An index is a matrix $M$ holding one row per entry, so the similarity of a query vector $v$ to every entry at once is the single matrix-vector product $M v$. For a thousand entries that amounts to a thousand dot products of 384 terms each, a few milliseconds in NumPy. Approximate nearest-neighbor structures and vector databases begin to repay their complexity only somewhere above a hundred thousand vectors, so the package stores a plain array and multiplies.

Although a cosine can in principle take any value between $-1$ and $1$, the vectors of a contrastively trained model do not spread over the whole sphere. They occupy a comparatively narrow cone, and two entirely unrelated pieces of English prose therefore score somewhere between 0.5 and 0.7. Negative values do not generally occur. Two texts as unrelated as a sourdough recipe and a set of municipal drainage bylaws still score above 0.4. A cosine of 0.68 does not mean "68 percent relevant" and is not by itself evidence of anything. Absolute values carry no meaning, and values obtained for different queries are not comparable with one another. Only the ordering within a single comparison, together with the size of the gaps, is informative. The two statistical procedures described below exist in order to convert that ordering into an actionable quantity.

## The asymmetry between queries and documents

A three-word search phrase and a two-hundred-word abstract are different kinds of text, and a model that treats them alike will place the phrase among other short phrases rather than among the documents it ought to retrieve. The `bge` model family is trained to account for this asymmetry: documents are embedded as they stand, while a search query is first prefixed with the fixed instruction `Represent this sentence for searching relevant passages: `, which the model saw on the query side throughout training. The prefix marks the text as a question and places it where its answers lie.

The package applies the prefix itself, in `embed_query`, and only when embedding a search phrase. Relevance scoring compares one paper against other papers, a document-to-document comparison, so the candidate's text (e.g., title and abstract) is embedded without it.

## The contents of an index

BibDeskParser supports any number of named "indexes", where each index is a matrix with an embedding vector in each row, for each entry of the library. Everything that search and scoring do afterwards is arithmetic on that matrix. What distinguishes one index from another is which text gets assembled. A library may hold several indexes over the same entries, one built from titles and abstracts, another from long summaries kept in companion files. Each is a separate matrix, and any one call works against exactly one of them, named in the call or taken from the `search_index` and `score_index` settings.

Indexes are defined in the [`bibdeskparser.toml` configuration](config-semantic), under `[semantic.indexes]`. Each entry of that table gives an index a name and an ordered list of *sources*:

```toml
[semantic.indexes]
summary = ["summary"]
annotated = ["title", "abstract", "note"]
```

A source names a place to take text from, and is evaluated separately for every entry. It is either an entry field, such as `title`, `abstract`, or `note`, whose value is then used directly, or an [entry asset class](external-assets), in which case the content of that entry's companion file is read from disk. Asset classes are declared in the `[assets]` table of the same configuration file; should a name be declared as both, the asset takes precedence. A name that is neither is a configuration error, reported when the index is built, and so is a *library* asset class, which is one text for the whole library and would contribute the same words to every row.

An index name becomes a filename, so it is restricted to letters, digits, hyphens, and underscores.

The texts that the sources yield are joined in the order listed, separated by a blank line, and embedded as a single text. A source for which an entry has nothing is skipped. An entry that none of the sources covers has no text at all and is left out of that index; it can still be found through the lexical leg of a hybrid search. Beside the matrix, a manifest records which sources actually contributed for each entry. That record is what relevance scoring uses to pick out the entries whose row was built from both a title and an abstract.

One index exists without being configured at all. It is named `default` and is equivalent to `["title", "abstract"]`. The name is reserved and the index cannot be redefined, because its rows have precisely the shape of an incoming candidate paper, which is what allows relevance scoring to calibrate against them (see below). Since every entry has a title, this index covers the whole library, with entries lacking an abstract appearing as title-only rows.

Combining a nearly universal source with a sparse one, as in `["title", "summary"]`, yields rows of very different lengths and registers. For an index used for searching this is a reasonable trade for coverage. For an index used as the target of relevance scoring, sources of matching coverage are preferable, in practice a single one, so that the raw similarities remain comparable from row to row.

### Long texts and chunking

The model accepts at most 512 *tokens*. A token is approximately a word or a fragment of one, so 512 tokens correspond to a few hundred words: a title and abstract fit comfortably, whereas a 500-word summary runs to roughly 650 to 800 tokens and does not. Text beyond the limit would simply be discarded.

The package therefore divides an over-long text into chunks that individually fit, embeds them separately, and combines the chunk vectors into a single entry vector by averaging them component by component and rescaling the result to unit length. The average of several unit vectors points, loosely speaking, in their common direction, which is what makes it a reasonable summary of the pieces.

Texts are handed to the model in batches rather than one at a time, and every sequence in a batch is padded to the length of the longest one in it. A batch that mixes a one-word title with a 300-word abstract therefore spends most of its effort on padding, which is why the batch is kept small: on the example database, batches of 16 embed about a third faster than batches of 256. The batch size also perturbs the vectors in the fourth decimal, through the order in which floating-point sums are accumulated, so it is recorded in the index fingerprint and a change to it rebuilds. The perturbation is some four orders of magnitude below the cosine gaps that separate entries, so it cannot reorder a ranking.

Division proceeds from the most meaningful boundary to the least: at markdown headings first, then at blank lines between paragraphs, and, only as a last resort, between individual words. At each level the pieces are packed back together greedily, each chunk filled as close to the 512-token budget as it will go, stopping just below it: the tokenizer truncates at 512, so a count of exactly 512 is what a text of 512 tokens and a text of 5000 both report, and only a count below that establishes that a piece survives whole. The packing is deliberate. Text that ends up within one chunk is combined by the model itself, which reads it in context, whereas text distributed over several chunks is combined only by the arithmetic average applied afterwards. Fuller chunks leave more of the combination to the model, and they also cause the entry vector to reflect how much text each part contributes rather than the number of sections the text happens to be divided into.

## Which similarities carry information

Given a query, a cosine is available for every entry. Which of them should count as matches?

A fixed threshold is not a workable criterion, because the background level is not fixed: it depends on the query, and it already lies between 0.5 and 0.7 for texts with nothing in common. What does hold for any particular query is that only a small fraction of the library is about what that query asks for. Most of the $N$ cosines are therefore contributed by entries irrelevant to it, and those form a compact bulk, spread only by incidental vocabulary overlap. The few entries that are actually relevant, if any, appear above that bulk as a thin tail.

The package accordingly locates the bulk from the numbers themselves. Write $s_1, \dots, s_N$ for the cosines and $\tilde{s}$ for their median. The width of the bulk is estimated by the *median absolute deviation*,

$$\mathrm{MAD} = \operatorname{median}_i \left| s_i - \tilde{s} \right|,$$

which is the median distance of the values from their own center. For normally distributed data the MAD is smaller than the standard deviation by a fixed factor, since half of a normal distribution's mass lies within $0.6745\,\sigma$ of the mean. Multiplying by $1/0.6745 = 1.4826$ therefore converts the MAD into an estimate of $\sigma$ on the familiar scale. An entry counts as a match when

$$s_i > \tilde{s} + 2.5 \times 1.4826 \times \mathrm{MAD},$$

that is, when it lies more than two and a half estimated standard deviations above the center of the bulk.

The value is calibrated against measurement rather than against the normal distribution. On a 125-paper bibliography spanning five topics, the entries a topical query ought to return run from $3.9\sigma$ down to about $2.5\sigma$, while queries from other fields altogether reach only $1.9\sigma$ and $2.1\sigma$. A cut at 2.5 admits the matches and still rejects the unrelated queries; a cut at 3.5 sits above almost all of the signal and returns nothing for most real queries. The margin below the cut is a few tenths of a $\sigma$, so an occasional unrelated entry does get through, which is the price of a criterion that answers at all.

The normal figure for a one-sided $2.5\sigma$ cut, about one value in 161, overstates the accidents to expect, because the bulk has thinner tails than a normal distribution: those 125 unrelated cosines peaked at $1.9\sigma$ and $2.1\sigma$ where a normal bulk of that size would be expected to reach $2.7\sigma$.

The criterion needs a bulk to locate, so it needs a library. On a handful of entries the median and the MAD are estimated from a handful of numbers, and an ordinary above-median cosine clears any threshold; a library of that size is better served by reading all of it.

The use of the median and the MAD in place of the mean and the standard deviation is the essential point of the construction. The latter two are displaced by the very values the procedure is meant to isolate: a handful of strong matches raises the mean and inflates the standard deviation, which raises the threshold, which may in turn conceal the matches responsible. The median and the MAD are unaffected until more than half the sample consists of outliers, so the matches cannot suppress themselves. The reasoning is the same as that behind quoting a median for a measurement series containing a few extreme readings.

As an illustration, suppose the bulk has median 0.55 and an estimated width of 0.025. The cut then lies near $0.55 + 2.5 \times 0.025 = 0.61$, so that a handful of entries scoring between 0.65 and 0.73 pass while the remainder of the library does not.

Two consequences follow. A query unrelated to the library is all bulk and no tail, so nothing passes and the result is empty; this is the correct answer, obtained at no additional cost from numbers already computed. The `limit` is a maximum only: three results in response to a request for ten means that only three entries stood out.

The one weak point is a query so broad that a sizeable fraction of the library really is related to it. Those entries widen the bulk themselves, and only the strongest few remain clear of it. This is acceptable, since such a query does not discriminate to begin with, and the lexical ranking described next still orders whatever the cut discards.

## Combining two rankings

Character matching and vector similarity fail under different circumstances, which is what makes their combination worthwhile. Domain-specific queries are rich in exact terms, for which matching the characters is precisely right and for which an embedding may blur the term into its neighborhood. A query phrased in the reader's own words, conversely, finds nothing lexically and everything semantically. Searching with `hybrid=True`, the default, performs both and merges the results.

The two rankings cannot simply be added: one yields cosines in a compressed band, the other the `(rung, fine)` score of {py:meth}`~bibdeskparser.Library.search`, and the scales bear no relation to each other. *Reciprocal rank fusion* avoids the problem by discarding the scores and retaining only the positions. An entry appearing at rank $r$ in one of the rankings receives from it a contribution

$$\frac{1}{60 + r}$$

to its fused score, and the contributions of the two rankings are summed. Sorting by that sum gives the final order.

The constant 60 is what causes the procedure to behave as a consensus vote. Since $1/61 = 0.0164$ and $1/62 = 0.0161$ are nearly equal, ranking first rather than second within one ranking is worth very little, whereas appearing in both rankings at all is worth a great deal: an entry ranked third semantically and fifth lexically scores $1/63 + 1/65 = 0.0313$, comfortably above an entry ranked first semantically and absent lexically at $0.0164$. A plain $1/r$ would reverse this and render the leading entry of each ranking nearly unbeatable. The value originates in the paper that introduced the method (Cormack, Clarke, and Büttcher, SIGIR 2009) and has been used unchanged since.

The remaining behavior follows from the formula. An entry found by only the lexical ranking still appears, whether the index omits it entirely or holds a row whose cosine the match cut rejected. Its reported cosine is `null` in both cases: a below-cut cosine is a number the procedure has just declined to treat as a match, and printing it would present a non-match as one. A query with no semantic matches reduces to the plain lexical order. And the fused order need not decrease monotonically in the reported cosine, since the cosine is not what determined the sorting.

## Calibrating a similarity into a readable score

Relevance scoring meets the same difficulty as search, in a sharper form. A candidate paper's raw similarity to the entries it is compared against falls somewhere in the compressed band between 0.5 and 0.7, from which no reader can determine whether the candidate belongs.

Scoring always runs against a *target*, which is either the whole library or a *collection* within it. A collection is named by a static group, by a keyword, or as an explicit list of citation keys, and naming several of those pools their members into one. The choice changes what the resulting number means, for a reason that only becomes visible once the number is defined.

The raw measure is straightforward. The candidate's title and abstract are embedded as a single document, the cosine to every entry of the target set is computed, and the mean of the $k$ largest of these is the raw value. Using the top $k$ rather than a single centroid matters: averaging the vectors of a multi-topic library first would produce a direction describing nothing in particular. Using several neighbors rather than only the nearest prevents a single fortunate match from determining the result. So the measure asks how close the candidate is to a neighborhood of the target, and $k$ sets how wide that neighborhood is: it defaults to 10, is clamped to the size of the collection so that a collection of one reduces to the plain cosine, and is adjustable per call. Those same $k$ entries are what the report lists as `nearest`, so the neighbors behind any score can be read off it.

The substance of the method is what the raw value is compared against. A measurement in an experiment is meaningless without a control, and the same applies here; the control is constructed from data already at hand. The *probes* are the library's own papers, specifically those rows of the `default` index that carry both a title and an abstract, since those are the rows shaped like an incoming candidate. Each probe is then scored by exactly the procedure just applied to the candidate: the same target set, the same $k$, and the probe's own row removed from the target side so that it cannot match itself. Each probe thereby answers the question of what that paper would have scored had it arrived on the same day as a fresh preprint.

Those probe values together constitute the null distribution, and the candidate's reported score is its percentile within that distribution: the percentage of the library's own papers scoring lower. An unrelated candidate scores near 0. A score of 82.7 states that the candidate lies topically closer to the target than 82.7 percent of the library's papers would have.

A library in which no entry carries an abstract has no probes at all, and a percentile of an empty distribution does not exist. The score is then `None` rather than 0, with a warning, since a 0 there would be indistinguishable from a candidate the library has nothing to do with.

Calibration of this kind is exact rather than approximate. Suppose the target index holds long summaries while the candidate consists of a short title and abstract. Every raw cosine is depressed by that mismatch of register. The probes, however, are title-and-abstract rows as well, and they are scored against the same summaries, so their values are depressed by the same amount. The distortion cancels in the ranking and the percentile survives it. This is why percentiles are comparable across different collections and different indexes while raw cosines are not.

The cost is a single matrix product over roughly a thousand probe vectors, a few milliseconds. Nothing is precomputed and nothing is stored, so the calibration cannot fall out of step with the index it is computed from.

### Reading a score

Percentiles against the whole library are a weak signal by construction. Every library paper is scored against the library, so their percentiles are distributed uniformly between 0 and 100 however coherent the library may be. A whole-library score is therefore useful as a rejection gate, since a candidate near 0 has no bearing on the library's subject matter, and as a duplicate check, since a score near 100 accompanied by a nearest-neighbor cosine near 1.0 indicates that the paper is already present. A middling value such as 71 says little.

Scoring against a topic group is considerably more informative, because a single whole-library number dilutes a strong fit to one topic across every other topic in the library. Whenever the target is a collection rather than the whole library, the report adds the `members` band: the quartiles of the collection members' own percentiles, computed exactly as the candidate's. The band is what turns a percentile into a statement about membership:

- At or above the group's median, the candidate scores like a typical member.
- At or above the first quartile, it scores like a weaker but legitimate member.
- Below the first quartile, it is topically adjacent yet weaker than any actual member of the group.

The absolute position of the band varies considerably between groups. A tight, well-defined topic may have all its members above 92, while a diffuse one spans 40 to 90. The criterion is therefore the candidate's position relative to *that group's* band, never a fixed percentile.

## Limits of the method

Cosine similarity measures topical proximity and nothing else. It cannot establish whether a candidate paper extends the work it resembles, contradicts it, or merely overlaps with it, since a direction of that kind is not encoded in an angle between two vectors. Reading the nearest-neighbor list and forming that judgment remains the responsibility of a human reader or an agent; the task of the package ends with producing a number that means the same thing on every occasion.

A second limit is less obvious. The model was trained on generic English by people who had never seen the library it is applied to, so "similar" means similar in a general sense, which need not coincide with the sense in which a particular library treats two papers as related. This is what keeps the feature free of any training step, of any stored model of a user's preferences, and of any per-user state, and it is also what bounds it. Should the percentiles begin to misclassify papers of interest, the established remedy is to fit a small linear model on top of these same frozen vectors, taking a topic group's own members as positive examples and the remainder of the library as negatives. That is a separate feature and is not implemented here; the zero-shot percentile is to be tried first, and found insufficient, before anything of the kind is warranted.

## Stored artifacts and rebuilding

Each index writes two files into the index directory, which defaults to the `.bib` path with its extension replaced by `.semantic` (so `refs.semantic/` beside `refs.bib`) and is configurable as [`index_dir`](config-semantic). For an index named `default` they are:

- `default.npz`, the matrix of unit vectors, one row per citation key. For a thousand entries it occupies about 1.5 MB.
- `default.json`, the manifest, recording for each key the sources that actually contributed and a hash of the embedded text, together with the index *fingerprint*: the source list, the model, the model file, the vector dimension, the batch size, and the `fastembed` version.

The directory holds derived data that `build_semantic_indexes` owns and rewrites at will. It is deliberately not declared as an `[assets]` class, since those describe files produced elsewhere that the package only reads, and the missing-asset audit would report every index not yet built.

Refreshing is precise and proceeds per entry. A key whose text hashes to the stored value retains its vector, a changed or new key is re-embedded, and a key the library no longer holds is dropped, which is also what prevents a [`rekey`](cli-rekey) from leaving a stray row behind. A change to the fingerprint, whether a different source list, a different model, or a different `fastembed` release, rebuilds that index as a whole, so that vectors produced by different models are never mixed within one matrix. Including the source list in the fingerprint is what allows an edited index definition to register as a single rebuild rather than as a thousand individual hash mismatches.

Searching or scoring with an index that has fallen behind the library still works, using the stored vectors, and warns while naming the keys concerned. A row belonging to an entry that has since been deleted is the one case that cannot be honored that way: it may still rank, but there is no entry to return for it, so it is passed over. Reproducibility rests on the computation graph being a frozen artifact: a pinned `fastembed` release produces identical vectors from run to run, and differences between machines amount to floating-point noise in the last place, far too small to reorder a ranking.

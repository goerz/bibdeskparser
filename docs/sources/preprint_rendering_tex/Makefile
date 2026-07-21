# Rebuild the rendering-comparison document (part of the Sphinx
# documentation, linked from the "Preprints" page).

all: preprints.pdf

preprints.pdf: preprints.tex refs.bib
	latexmk -pdf preprints.tex
	latexmk -c preprints.tex
	rm -f preprints.bbl preprintsNotes.bib

clean:
	latexmk -c preprints.tex
	rm -f preprints.bbl preprintsNotes.bib

distclean: clean
	rm -f preprints.pdf

.PHONY: all clean distclean

echo "# DOCTR - deploy documentation"
echo "## Generate main html documentation"
tox -e docs -- -b html -d build/doctrees source build/html
echo "## Generate documentation downloads"
mkdir docs/build/html/download
echo "### [epub]"
tox -e docs -- -b epub -d build/doctrees source build/epub
cp docs/build/epub/BibDeskParser.epub docs/build/html/download
echo "### [htmlzip]"
tox -e docs -- -b html -d build/doctrees source build/BibDeskParser.html
cd docs/build/
zip -r BibDeskParser.html.zip ./BibDeskParser.html
cd ../../
cp docs/build/BibDeskParser.html.zip docs/build/html/download
echo "### [pdf (via latex)]"
tox -e docs -- -b latex -d build/doctrees source build/tex
cd docs/build/tex
texliveonfly BibDeskParser.tex
pdflatex BibDeskParser.tex
cd ../../../
cp docs/build/tex/BibDeskParser.pdf docs/build/html/download
# deploy with doctr
echo "## pip install doctr"
python -m pip install doctr
echo "## doctr deploy"
if [[ -z "$TRAVIS_TAG" ]]; then
    DEPLOY_DIR="$TRAVIS_BRANCH"
else
    DEPLOY_DIR="$TRAVIS_TAG"
fi
python -m doctr deploy --key-path docs/doctr_deploy_key.enc \
    --command="git show $TRAVIS_COMMIT:.travis/docs_post_process.py > post_process.py && git show $TRAVIS_COMMIT:.travis/versions.py > versions.py && python post_process.py" \
    --built-docs docs/build/html --no-require-master --build-tags "$DEPLOY_DIR"
echo "# DOCTR - DONE"

Logging module to understand failures
=====================================

Syntax of bibtex files is simple but there are many possible variations. This library probably fails for some of them.

Bibtexparser includes a large quantity of debug messages which helps to understand why and where the parser fails.
The example below can be used to print these messages in the console.

.. code-block:: python
    import logging
    import logging.config

    logger = logging.getLogger(__name__)

    logging.config.dictConfig({
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'standard': {
                'format': '%(asctime)s [%(levelname)s] %(name)s %(funcName)s:%(lineno)d: %(message)s'
            },
        },
        'handlers': {
            'default': {
                'level':'DEBUG',
                'formatter': 'standard',
                'class':'logging.StreamHandler',
            },
        },
        'loggers': {
            '': {
                'handlers': ['default'],
                'level': 'DEBUG',
                'formatter': 'standard',
                'propagate': True
            }
        }
    })


    if __name__ == '__main__':
        bibtex = """@ARTICLE{Cesar2013,
          author = {Jean César},
          title = {An amazing title},
          year = {2013},
          month = jan,
          volume = {12},
          pages = {12--23},
          journal = {Nice Journal},
          abstract = {This is an abstract. This line should be long enough to test
        	 multilines...},
          comments = {A comment},
          keywords = {keyword1, keyword2},
        }
        """

        with open('/tmp/bibtex.bib', 'w') as bibfile:
            bibfile.write(bibtex)

        from bibtexparser.bparser import BibTexParser

        with open('/tmp/bibtex.bib', 'r') as bibfile:
            bp = BibTexParser(bibfile)
            print(bp.get_entry_list())
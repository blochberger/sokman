.PHONY: all clean
.SUFFIXES: .dot .pdf .svg .tex

DB = db.sqlite3
DOT = dot
DOTTOTEX = dot2tex
MANAGE = ./manage.py
TAGDAG = $(MANAGE) tagdag --threshold 1

all: graphs/citations.svg graphs/sok.svg

clean:
	rm -f graphs/*.dot
	rm -f graphs/*.svg

.dot.pdf:
	$(DOT) -Tpdf -o$*.pdf $<

.dot.svg:
	$(DOT) -Tsvg -o$*.svg $<

.dot.tex:
	$(DOTTOTEX) -f tikz --usepdflatex $< > $@

graphs/citations.dot: $(DB) sok/management/commands/citations.py
	$(MANAGE) citations --pk --min-citations 10 > $@

graphs/sok.dot: $(DB) sok/management/commands/tagdag.py
	$(TAGDAG) > $@

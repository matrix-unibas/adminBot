# Builds the admin bot handbook in two versions from the same sources:
#   build/handbook-professors.pdf  for professors and TAs
#   build/handbook-technical.pdf   the same plus how the bot works (architecture, Synapse, security)
# Needs latexmk and pdflatex (MacTeX or TeX Live).

LATEXMK ?= latexmk
FLAGS   := -pdf -interaction=nonstopmode -halt-on-error -file-line-error -outdir=build
SOURCES := preamble.tex content.tex $(wildcard chapters/*.tex)

.PHONY: all professors technical clean watch-professors watch-technical

all: professors technical

professors: build/handbook-professors.pdf

technical: build/handbook-technical.pdf

build/handbook-%.pdf: handbook-%.tex $(SOURCES)
	$(LATEXMK) $(FLAGS) $<

# Rebuild on every save (Ctrl-C to stop).
watch-professors:
	$(LATEXMK) $(FLAGS) -pvc handbook-professors.tex

watch-technical:
	$(LATEXMK) $(FLAGS) -pvc handbook-technical.tex

clean:
	rm -rf build

TEX := src/main.tex
BUILD_DIR := build
PDF := $(BUILD_DIR)/main.pdf
HANDOUT_PDF := $(BUILD_DIR)/main-handout.pdf

.PHONY: all pdf handout clean

all: pdf

pdf: $(PDF)

handout: $(HANDOUT_PDF)

$(PDF): $(TEX)
	mkdir -p $(BUILD_DIR)
	pdflatex -halt-on-error -output-directory=$(BUILD_DIR) $(TEX)
	pdflatex -halt-on-error -output-directory=$(BUILD_DIR) $(TEX)

$(HANDOUT_PDF): $(TEX)
	mkdir -p $(BUILD_DIR)
	pdflatex -halt-on-error -jobname=main-handout -output-directory=$(BUILD_DIR) "\def\HANDOUTMODE{}\input{$(TEX)}"
	pdflatex -halt-on-error -jobname=main-handout -output-directory=$(BUILD_DIR) "\def\HANDOUTMODE{}\input{$(TEX)}"

clean:
	rm -rf $(BUILD_DIR)

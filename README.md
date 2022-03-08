# ITEMAL

ITEMAL performs item analyses of individual test questions as well as entire tests. It can be used to analyze data collected on optical scan sheets and already processed by the test scoring program or any scored test data that has been placed in a disk file.  This is a Python translation of the original _ancient_ Fortran code.

See [this page](https://services.udel.edu/TDClient/32/Portal/KB/ArticleDet?ID=386) for documentation of the input file format, etc.

## Usage

Traditionally, **itemal** was executed with the input directed to its stdin with all output going to stdout (which can be redirected to a file):

```
$ itemal < itemal.in > itemal.out
```

The Python version follows this same behavior but augments it with the ability to process multiple input files in one invocation and send the output to multiple files:

```
$ itemal.py --help
usage: itemal.py [-h] [--input <file|->] [--output <file|->] [--append]

Statistical analyses of multiple-choice responses.

optional arguments:
  -h, --help            show this help message and exit
  --input <file|->, -i <file|->
                        an input file to be processed; may be used multiple
                        times, "-" implies standard input and may be used only
                        once (and is the default if no input files are
                        provided)
  --output <file|->, -o <file|->
                        an output file to write data to; may be used multiple
                        times, "-" implies standard output (and is the default
                        if no input files are provided) NOTE: if the number of
                        output files is fewer than the number of input files,
                        the final output file will have multiple analyses
                        written to it
  --append, -a          always append to output files

$ itemal.py --input itemal.in --output itemal.out
```

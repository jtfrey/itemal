# ITEMAL

ITEMAL performs item analyses of individual test questions as well as entire tests. It can be used to analyze data collected on optical scan sheets and already processed by the test scoring program or any scored test data that has been placed in a disk file.  This is a Python translation of the original _ancient_ Fortran code in [itemal.f](itemal.f).

See [this page](https://services.udel.edu/TDClient/32/Portal/KB/ArticleDet?ID=386) for documentation of the input file format, etc.  The [itemal.in](examples/itemal.in) included in this repository may be more easily understood, though, as the documentation page doesn't agree 100% with the state of the itemal Fortran program.

## Usage

Traditionally, **itemal** was executed with the input directed to its stdin with all output going to stdout (which can be redirected to a file):

```
$ itemal < examples/itemal.in > itemal.out
```

The Python version follows this same behavior but augments it with the ability to process multiple input files in one invocation and send the output to multiple files:

```
$ ./itemal.py --help
usage: itemal.py [-h] [--input <file|->] [--output <file|->] [--append] [--format <format-id>]
                 [--input-format <format-id>] [--output-format <format-id>]

Statistical analyses of multiple-choice responses.

optional arguments:
  -h, --help            show this help message and exit
  --input <file|->, -i <file|->
                        an input file to be processed; may be used multiple times, "-" implies standard input and may
                        be used only once (and is the default if no input files are provided)
  --output <file|->, -o <file|->
                        an output file to write data to; may be used multiple times, "-" implies standard output (and
                        is the default if no input files are provided) NOTE: if the number of output files is fewer
                        than the number of input files, the final output file will have multiple analyses written to
                        it
  --append, -a          always append to output files
  --format <format-id>, -f <format-id>
                        file format to read and write (fortran is the default): fortran, json, json+pretty, yaml
  --input-format <format-id>, -I <format-id>
                        file format to read (fortran is the default): fortran, json, json+pretty, yaml
  --output-format <format-id>, -O <format-id>
                        file format to write (fortran is the default): fortran, json, json+pretty, yaml, excel

$ itemal.py --input examples/itemal.in --output itemal.out
```

the second command is essentially the same as the traditional invocation above.  The input and output formats *can* be mixed — a Fortran input file can be read and YAML output can be generated:

```
$ ./itemal.py --input-format=fortran --output-format=yaml < examples/itemal.yaml
course-name: 'PSY101 10 '
exam-date: 2012-09-13 00:00:00
exam-id: '1'
exam-sections:
-   answer-key: [1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4, 1, 2, 3, 4]
    options: {is-order-reversed: false, number-of-copies: 1, should-eval-full-exam-only: false}
       :
```

### JSON

The JSON file format (see [itemal.json](examples/itemal.json) and  (see [itemal.json.out](examples/itemal.json.out)) ) can be chosen for input and ouput by using the `--format=json` flag.

### YAML

The YAML file format (see [itemal.yaml](examples/itemal.yaml) and [itemal.yaml.out](examples/itemal.yaml.out)) is conditionally available:  if your Python environment has the PyYAML module installed, the "yaml" file format will be present in the help text as above and can be selected using `--format=yaml`.  The lack of PyYAML is also readily apparent if you try to use that format:

```
$ ./itemal.py --format=yaml < examples/itemal.yaml
ERROR:  file format "yaml" is not available
```

### Excel

Output to an Excel spreadsheet is conditionally available:  if your Python environment has the Pandas module installed, the "excel" file format will be present (for output only) in the help text as above and can be selected using `--output-format=excel`.  The **openpyxl** engine is required.  It is best to provide an explicit output file name using e.g. `--output=examples/itemal.xlsx`:

```
$ ./itemal.py -I fortran -i examples/itemal.in -O excel -o examples/itemal.xlsx
```

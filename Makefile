.PHONY: fmt lint test

fmt:
\tblack .
\truff check . --fix

lint:
\truff check .

test:
\tpytest -q

from time import time
import sys
import logging

### XXX Fix for Python 3.8 bug (https://github.com/prompt-toolkit/python-prompt-toolkit/issues/1023)
import asyncio
import selectors
selector = selectors.SelectSelector()
loop = asyncio.SelectorEventLoop(selector)
asyncio.set_event_loop(loop)
### XXX End of fix

from . import Preql
from . import pql_objects as objects
from . import pql_ast as ast
from .api import TablePromise
from .exceptions import PreqlError, pql_ExitInterp, pql_SyntaxError_PrematureEnd, pql_SyntaxError
from .pql_types import Object




class RowWrapper:
    def __init__(self, row):
        self._row = row

    def __repr__(self):
        return self._row.repr()

    def __getitem__(self, item):
        return self._row.getattr(item)

    def __getattr__(self, attr):
        return self[attr]

    def __iter__(self):
        return iter(self._row)

    def __getstate__(self):
        return self._row
    def __setstate__(self, x):
        self._row = x


class TableWrapper:
    def __init__(self, pql_table, interp):
        self._pql_table = pql_table
        self._interp = interp

    def __repr__(self):
        return self._pql_table.repr(self._interp)

    def json(self):
        return [row.attrs for row in self._query()]

    def _query(self):
        return self._pql_table.query(self._interp, None)

    def __iter__(self):
        return (RowWrapper(row) for row in self._query())

    def __len__(self):
        return self._pql_table.count(self._interp).value


from prompt_toolkit import prompt
from prompt_toolkit import PromptSession
from pygments.lexers.python import Python3Lexer
from pygments.lexers.go import GoLexer
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.filters import Condition
from prompt_toolkit.application.current import get_app

from .parser import parse_stmts



def start_repl(p, prompt=' >> '):
    print("Welcome to the Preql REPL. Type help() for help")
    save_last = '_'   # XXX A little hacky

    try:
        session = PromptSession()

        @Condition
        def multiline_filter():
            text = get_app().layout.get_buffer_by_name('DEFAULT_BUFFER').text
            if text:
                try:
                    s = parse_stmts(text, '<repl>')
                except pql_SyntaxError as e:
                    return True
                except Exception as e:
                    print(e)
                    return False

            return False

        while True:
            # Read
            try:
                code = session.prompt(prompt, lexer=PygmentsLexer(GoLexer), multiline=multiline_filter)
                if not code.strip():
                    continue

                start_time = time()
                try:
                    # Evaluate (Really just compile)
                    res = p.run_code(code, '<repl>')

                    # Print
                    if res is not None and res is not objects.null:
                        assert isinstance(res, Object), (res, type(res))

                        if save_last:
                            p.interp.set_var(save_last, res)

                        res = res.repr(p.interp.state)
                        print(res)

                except PreqlError as e:
                    print(e)
                    # p.interp.set_var('_e', objects.ExceptionInstance(e))
                    continue
                except pql_ExitInterp as e:
                    return
                except Exception as e:
                    print("Error:")
                    logging.exception(e)
                    raise
                    # continue

                duration = time() - start_time
                if duration > 1:
                    print("(Query took %.2f seconds)" % duration)

            except KeyboardInterrupt:
                print("Interrupted (Ctrl+C)")



    except (KeyboardInterrupt, EOFError):
        print('Exiting Preql interaction')


def main(script=None):
    # p = Preql(db)
    p = Preql()
    if script:
        p.load(script)
    start_repl(p)

if __name__ == '__main__':
    main(*sys.argv[1:])
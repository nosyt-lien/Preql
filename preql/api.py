from contextlib import contextmanager

import rich.table
import rich.markup

from . import settings
from . import pql_ast as ast
from . import pql_types as types
from . import pql_objects as objects
from . import exceptions as exc
from .interpreter import Interpreter
from .evaluate import cast_to_python, localize, evaluate, new_table_from_rows
from .interp_common import create_engine, call_pql_func, State
from .pql_types import T



def _make_const(value):
    # t = types.Primitive.by_pytype[type(value)]
    t = types.from_python(type(value))
    return ast.Const(None, t, value)

def _call_pql_func(state, name, args):
    count = call_pql_func(state, name, args)
    return cast_to_python(state, count)

TABLE_PREVIEW_SIZE = 16
LIST_PREVIEW_SIZE = 128
MAX_AUTO_COUNT = 10000



def table_limit(self, state, limit, offset=0):
    return call_pql_func(state, '_core_limit_offset', [self, _make_const(limit), _make_const(offset)])


def _html_table(name, count_str, rows, offset):
    header = 'table '
    if name:
        header += name
    if offset:
        header += f'[{offset}..]'
    header += f" {count_str}"
    header = f"<pre>table {name}, {count_str}</pre>"

    if not rows:
        return header

    cols = list(rows[0])
    ths = '<tr>%s</tr>' % ' '.join([f"<th>{col}</th>" for col in cols])
    trs = [
        '<tr>%s</tr>' % ' '.join([f"<td>{v}</td>" for v in row.values()])
        for row in rows
    ]

    return '%s<table>%s%s</table>' % (header, ths, '\n'.join(trs))


def _rich_table(name, count_str, rows, offset, colors=True, show_footer=False):
    header = 'table '
    if name:
        header += name
    if offset:
        header += f'[{offset}..]'
    header += f" {count_str}"

    if not rows:
        return header

    table = rich.table.Table(title=rich.markup.escape(header), show_footer=show_footer)

    # TODO enable/disable styling
    for k, v in rows[0].items():
        kw = {}
        if isinstance(v, (int, float)):
            kw['justify']='right'

        if colors:
            if isinstance(v, int):
                kw['style']='cyan'
            elif isinstance(v, float):
                kw['style']='yellow'
            elif isinstance(v, str):
                kw['style']='green'

        table.add_column(k, footer=k, **kw)

    for r in rows:
        table.add_row(*[rich.markup.escape(str(x)) for x in r.values()])

    return table


_g_last_table = None
_g_last_offset = 0
def table_more(state):
    if not _g_last_table:
        raise Signal.make(T.ValueError, state, None, "No table yet")

    return table_repr(_g_last_table, state, _g_last_offset)


def table_repr(self, state, offset=0):
    global _g_last_table, _g_last_offset

    assert isinstance(state, State), state
    count = _call_pql_func(state, 'count', [table_limit(self, state, MAX_AUTO_COUNT)])
    if count == MAX_AUTO_COUNT:
        count_str = f'>={count}'
    else:
        count_str = f'={count}'

    # if len(self.type.elems) == 1:
    #     rows = cast_to_python(state, table_limit(self, state, LIST_PREVIEW_SIZE))
    #     post = f', ... ({count_str})' if len(rows) < count else ''
    #     elems = ', '.join(repr_value(ast.Const(None, self.type.elem, r)) for r in rows)
    #     return f'[{elems}{post}]'

    rows = cast_to_python(state, table_limit(self, state, TABLE_PREVIEW_SIZE, offset))
    _g_last_table = self
    _g_last_offset = offset + len(rows)
    if self.type <= T.list:
        rows = [{'value': x} for x in rows]

    post = '\n\t...' if len(rows) < count else ''

    table_name = self.type.options.get('name', '')

    if state.fmt == 'html':
        return _html_table(table_name, count_str, rows, offset)
    elif state.fmt == 'rich':
        return _rich_table(table_name, count_str, rows, offset)

    assert state.fmt == 'text'
    return _rich_table(table_name, count_str, rows, offset, colors=False)

    # raise NotImplementedError(f"Unknown format: {state.fmt}")

objects.CollectionInstance.repr = table_repr


class TablePromise:
    def __init__(self, state, inst):
        self._state = state
        self._inst = inst
        self._rows = None

    def to_json(self):
        if self._rows is None:
            self._rows = cast_to_python(self._state, self._inst)
        assert self._rows is not None
        return self._rows

    def to_pandas(self):
        from pandas import DataFrame
        return DataFrame(self)

    def __eq__(self, other):
        return self.to_json() == other

    def __len__(self):
        return _call_pql_func(self._state, 'count', [self._inst])

    def __iter__(self):
        return iter(self.to_json())

    def __getitem__(self, index):
        if isinstance(index, slice):
            offset = index.start or 0
            limit = index.stop - offset
            return call_pql_func(self._state, '_core_limit_offset', [self._inst, _make_const(limit), _make_const(offset)])

        # TODO different debug log level / mode
        # inst = evaluate(self._state,
        res ,= cast_to_python(self._state, self[index:index+1])
        return res

    def __repr__(self):
        return repr(self.to_json()) #str(self._inst.repr(self._state))


def promise(state, inst):
    if inst.type <= T.table:
        return TablePromise(state, inst)

    return localize(state, inst)


class Interface:
    __name__ = "Preql"

    def __init__(self, db_uri=None, print_sql=settings.print_sql):
        if db_uri is None:
            db_uri = 'sqlite://:memory:'

        self._db_uri = db_uri
        self._print_sql = print_sql
        # self.engine.ping()

        engine = create_engine(self._db_uri, print_sql=self._print_sql)
        self._reset_interpreter(engine)

    def set_output_format(self, fmt):
        self.interp.state.fmt = fmt  # TODO proper api

    def _reset_interpreter(self, engine=None):
        if engine is None:
            engine = self.interp.state.db
        self.interp = Interpreter(engine)
        self.interp.state._py_api = self # TODO proper api

    def close(self):
        self.interp.state.db.close()

    def __getattr__(self, fname):
        var = self.interp.state.get_var(fname)
        if isinstance(var, objects.Function):
            def delegate(*args, **kw):
                assert not kw
                pql_args = [objects.from_python(a) for a in args]
                pql_res = self.interp.call_func(fname, pql_args)
                return self._wrap_result( pql_res )
            return delegate
        else:
            return self._wrap_result( evaluate( self.interp.state, var ))

    def _wrap_result(self, res):
        "Wraps Preql result in a Python-friendly object"
        assert not isinstance(res, ast.Ast), res
        return promise(self.interp.state, res)  # TODO session, not state

    def run_code(self, pq, source_file, **args):
        pql_args = {name: objects.from_python(value) for name, value in args.items()}
        return self.interp.execute_code(pq + "\n", source_file, pql_args)

    def __call__(self, pq, **args):
        res = self.run_code(pq, '<inline>', **args)
        if res:
            return self._wrap_result(res)

    def load(self, fn, rel_to=None):
        self.interp.include(fn, rel_to)

    @contextmanager
    def transaction(self):
        # TODO rollback
        try:
            yield self  # TODO new instance?
        finally:
            self.commit()

    def start_repl(self, *args):
        from .repl import start_repl
        start_repl(self, *args)

    def commit(self):
        return self.interp.state.db.commit()

    def _drop_tables(self, *tables):
        # XXX temporary method
        for t in tables:
            self.interp.state.db._execute_sql(T.null, f"DROP TABLE {t};", self.interp.state)

    def import_pandas(self, **dfs):
        for name, df in dfs.items():
            cols = list(df)
            rows = [[i.item() if hasattr(i, 'item') else i for i in rec]
                    for rec in df.to_records()]
            new_table_from_rows(self.interp.state, name, cols, rows)

    def load_all_tables(self):
        tables = self.interp.state.db.list_tables()
        for table_name in tables:
            table_type = self.interp.state.db.import_table_type(self.interp.state, table_name)
            inst = objects.new_table(table_type, table_name)
            self.interp.set_var(table_name, inst)




#     def _functions(self):
#         return {name:f for name,f in self.interp.state.namespace.items()
#                 if isinstance(f, ast.FunctionDef)}

#     def add_many(self, table, values):
#         cols = [c.name
#                 for c in self.interp.state.namespace[table].columns.values()
#                 if not isinstance(c.type, (ast.BackRefType, ast.IdType))]
#         return self.engine.addmany(table, cols, values)

#     def add(self, table, values):
#         return self.add_many(table, [values])

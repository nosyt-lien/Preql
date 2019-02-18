
from .api import SqliteEngine
from .interpreter import Interpreter

schema = """
table actors:
    first_name: string
    last_name: string
    gender: string 

table directors:
    first_name: string
    last_name: string

table movies:
    name: string
    year: integer
    rank: float

table movies_genres:
    movie_id: movies -> genres
    genre: string

table roles:
    actor_id: actors -> roles
    movie_id: movies -> roles
    role: string

# CREATE TABLE `directors_genres` (
#   `director_id` integer default NULL
# ,  `genre` varchar(100) default NULL
# ,  `prob` float default NULL
# );
# CREATE TABLE `movies_directors` (
#   `director_id` integer default NULL
# ,  `movie_id` integer default NULL
# );

count_by_year(T) = T {year => count(id)}

"""


def main():
    sqlengine = SqliteEngine('imdb.db')
    i = Interpreter(sqlengine)
    i.execute_code(schema)

    # print(i.call_func('count_best_movies_by_year', []))

    # print(i.eval_expr('movies [rank > 9] {year => count(id)}'))

    # print(i.eval_expr('movies [rank > 9] :limit(5) {name, genres}'))   # TODO: What do to? Aggregate? Error?

    # print(i.eval_expr('movies [rank > 9] :limit(5) {name => genres}'))    # TODO throw proper error, as id doesn't exist

    print(i.eval_expr('movies [rank > 9] :limit(5) {name => genres.genre}'))

    print(i.eval_expr('count(movies)'))
    print(i.eval_expr('count(movies [rank>9])'))

    print(i.eval_expr('movies :count()'))
    print(i.eval_expr('movies [rank>9] :count()'))

    # print(i.eval_query('count_by_year( movies [rank > 9] )'))     # TODO: Not implemented yet

main()
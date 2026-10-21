# packages/testing

Test helpers for every suite in this repository. Today: Postgres. A test gets databases of its own, each made from an
empty template and dropped when the test ends. Production runs on Postgres, so the tests do too.

```python
def test_something(pg_url):  # fixture: a new, empty database
    engine = db.connect(pg_url)


def fresh():  # a plain helper can make one too; it goes when the running test ends
    return db.connect(new_database_url())


@pytest.fixture(scope="module")  # wider than one test: create and drop it yourself
def seeded():
    url = create_database()
    yield url
    drop_database(url)
```

`new_pg_url` is the fixture form of `new_database_url`, for a test that wants more than one database. The fixtures load
as a pytest plugin once the package is installed (`pip install -e packages/testing`).

Where the server comes from:

- `TEST_DATABASE_URL`: a URL that may create databases. CI uses the Postgres service of its job.
- Without it: the development server at the repository root, which you start with
  `docker compose -f compose.dev.yml up -d`.

A database takes about 20 ms to create (`STRATEGY = FILE_COPY`, with fsync off on the development server), so tests
don't share one. It's dropped `WITH (FORCE)`, so an engine a test left open doesn't hold it up.
